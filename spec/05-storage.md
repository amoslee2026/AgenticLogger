# 05 - 存储后端设计

## 1. 概述

**双后端策略**，不再考虑 PostgreSQL：

| 后端 | 适用场景 | 特点 |
|------|---------|------|
| **JSONL** | 日志文件较小 | 流式、简单、可 grep |
| **SQLite + WAL** | 日志文件较大 / 多进程并发 | 索引快、并发安全 |

---

## 2. 日志文件命名

### 2.1 命名规则

**每次运行生成独立文件**，文件名包含程序标识和运行时间：

**格式**: `{program}_{command_or_pid}_{YYYY-MM-DD}_{HHmmss}.{ext}`

**示例**:
```
logs/
├── my_agent_main_2026-07-21_103000.jsonl
├── my_agent_worker_2026-07-21_103005.sqlite
├── build_script_npm_install_2026-07-21_110000.jsonl
├── coder_agent_pid12345_2026-07-21_113000.jsonl
└── test_suite_unit_2026-07-21_120000.sqlite
```

### 2.2 字段说明

| 字段 | 来源 | 示例 |
|------|------|------|
| `program` | `AgentLogger(program=...)` | `my_agent`, `build_script` |
| `command_or_pid` | `AgentLogger(command=...)` 或 PID | `main`, `npm_install`, `pid12345` |
| `YYYY-MM-DD` | 当前日期 | `2026-07-21` |
| `HHmmss` | 启动时间 | `103000` |
| `ext` | 存储后端 | `jsonl` 或 `sqlite` |

### 2.3 自动选择后端

```python
def generate_filename(program, command, log_dir, storage="auto"):
    """生成日志文件名"""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    
    if command is None:
        command = f"pid{os.getpid()}"
    
    # 清理非法字符
    safe_program = re.sub(r'[^\w\-]', '_', program)
    safe_command = re.sub(r'[^\w\-]', '_', command)
    
    if storage == "auto":
        # 根据预期大小自动选择
        ext = "sqlite" if estimated_size_large() else "jsonl"
    elif storage == "sqlite":
        ext = "sqlite"
    else:
        ext = "jsonl"
    
    filename = f"{safe_program}_{safe_command}_{date_str}_{time_str}.{ext}"
    return Path(log_dir) / filename
```

---

## 3. JSONL 后端

### 3.1 适用场景

- 日志文件较小 (< 100MB)
- 单进程写入
- 需要流式读取 (`tail -f`)
- 需要 `grep`/`jq` 处理

### 3.2 写入实现

```python
class JSONLBackend:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._write_global_context()
    
    def _write_global_context(self):
        """写入全局上下文 (文件头部)"""
        global_ctx = {
            "ts": datetime.now().isoformat(),
            "level": "__GLOBAL_CTX__",
            "msg": "Global context",
            "module": "__system__",
            "program": self.program,
            "command": self.command,
            "pid": str(os.getpid()),
            "rid": self.rid,
            "file": self.source_file,  # 程序文件路径
            # ... 其他全局信息
        }
        self._append(global_ctx)
    
    def write(self, entry: dict):
        """写入单条日志"""
        line = json.dumps(entry, ensure_ascii=False)
        with open(self.file_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    
    def write_batch(self, entries: list[dict]):
        """批量写入"""
        lines = [json.dumps(e, ensure_ascii=False) for e in entries]
        with open(self.file_path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
```

### 3.3 查询实现

```python
class JSONLReader:
    def query(self, **filters):
        """流式查询"""
        results = []
        limit = filters.pop('limit', 100)
        
        with open(self.file_path, 'r', encoding='utf-8') as f:
            for line in f:
                entry = json.loads(line)
                if self._match(entry, filters):
                    results.append(entry)
                    if len(results) >= limit:
                        break
        
        return results
```

---

## 4. SQLite + WAL 后端

### 4.1 适用场景

- 日志文件较大 (> 100MB)
- 多进程并发读写
- 需要索引加速查询
- 需要循环写入控制大小

### 4.2 WAL 模式

**WAL (Write-Ahead Logging)** 优势：
- 读写不互相阻塞
- 多进程可并发读写
- 写入性能提升 2-3x

```python
import sqlite3

class SQLiteBackend:
    def __init__(self, file_path: Path, wal_mode=True):
        self.file_path = file_path
        self.conn = sqlite3.connect(str(file_path), check_same_thread=False)
        
        if wal_mode:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")  # WAL 模式下安全级别
            self.conn.execute("PRAGMA busy_timeout=5000")   # 5 秒等待锁
        
        self._init_db()
        self._write_global_context()
    
    def _init_db(self):
        """初始化数据库"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                level TEXT NOT NULL,
                msg TEXT NOT NULL,
                module TEXT NOT NULL,
                tid TEXT,
                rid TEXT NOT NULL,
                pid TEXT NOT NULL,
                dur INTEGER,
                error_code TEXT,
                ctx TEXT,
                -- 类型特定字段
                tool TEXT,
                cmd TEXT,
                exit_code INTEGER,
                stdout TEXT,
                stderr TEXT,
                op TEXT,
                path TEXT,
                ok INTEGER,
                size INTEGER,
                choice TEXT,
                alts TEXT,
                reason TEXT,
                confidence REAL,
                lang TEXT,
                lines INTEGER,
                funcs TEXT,
                imports TEXT,
                from_task TEXT,
                to_task TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- 索引
            CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
            CREATE INDEX IF NOT EXISTS idx_logs_rid ON logs(rid);
            CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
            CREATE INDEX IF NOT EXISTS idx_logs_module ON logs(module);
            CREATE INDEX IF NOT EXISTS idx_logs_error_code ON logs(error_code);
            CREATE INDEX IF NOT EXISTS idx_logs_tool ON logs(tool);
            CREATE INDEX IF NOT EXISTS idx_logs_pid ON logs(pid);
            CREATE INDEX IF NOT EXISTS idx_logs_dur ON logs(dur);
            CREATE INDEX IF NOT EXISTS idx_logs_path ON logs(path);
            
            -- 堆栈跟踪表 (分离存储，保持主表轻量)
            CREATE TABLE IF NOT EXISTS tracebacks (
                tid TEXT PRIMARY KEY,
                traceback TEXT NOT NULL,
                exception_type TEXT,
                exception_msg TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- 全局上下文表
            CREATE TABLE IF NOT EXISTS global_context (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
    
    def write(self, entry: dict):
        """写入单条日志"""
        columns = self._extract_columns(entry)
        placeholders = ', '.join(['?' for _ in columns])
        col_names = ', '.join(columns.keys())
        
        self.conn.execute(
            f"INSERT INTO logs ({col_names}) VALUES ({placeholders})",
            list(columns.values())
        )
        self.conn.commit()  # WAL 模式下 commit 很快
    
    def _extract_columns(self, entry: dict) -> dict:
        """提取所有字段到列"""
        cols = {
            'ts': entry.get('ts'),
            'level': entry.get('level'),
            'msg': entry.get('msg'),
            'module': entry.get('module'),
            'tid': entry.get('tid'),
            'rid': entry.get('rid'),
            'pid': entry.get('pid'),
            'dur': entry.get('dur'),
            'error_code': entry.get('error_code'),
            'ctx': json.dumps(entry.get('ctx', {}), ensure_ascii=False),
        }
        
        # 类型特定字段
        if entry.get('level') == 'TOOL':
            cols.update({
                'tool': entry.get('tool'),
                'cmd': entry.get('cmd'),
                'exit_code': entry.get('exit'),
                'stdout': entry.get('stdout'),
                'stderr': entry.get('stderr'),
            })
        elif entry.get('level') == 'FILE_OP':
            cols.update({
                'op': entry.get('op'),
                'path': entry.get('path'),
                'ok': 1 if entry.get('ok') else 0,
                'size': entry.get('size'),
            })
        # ... 其他类型
        
        return cols
```

### 4.3 查询实现 (索引加速)

```python
class SQLiteReader:
    def query(self, **filters):
        """索引加速查询"""
        query = "SELECT * FROM logs WHERE 1=1"
        params = []
        
        # 精确匹配字段 (走索引)
        exact_fields = ['rid', 'level', 'module', 'error_code', 'tool', 'pid', 'tid']
        for field in exact_fields:
            if filters.get(field):
                if field == 'module' and '*' in filters[field]:
                    query += f" AND {field} LIKE ?"
                    params.append(filters[field].replace('*', '%'))
                else:
                    query += f" AND {field} = ?"
                    params.append(filters[field])
        
        # 范围查询
        if filters.get('min_dur'):
            query += " AND dur >= ?"
            params.append(filters['min_dur'])
        if filters.get('max_dur'):
            query += " AND dur <= ?"
            params.append(filters['max_dur'])
        
        # 时间范围
        if filters.get('since'):
            query += " AND ts >= ?"
            params.append(filters['since'])
        if filters.get('until'):
            query += " AND ts <= ?"
            params.append(filters['until'])
        
        # 排序
        order_by = filters.get('order_by', 'ts DESC')
        order_map = {
            'ts_asc': 'ts ASC',
            'ts_desc': 'ts DESC',
            'dur_desc': 'dur DESC',
        }
        query += f" ORDER BY {order_map.get(order_by, 'ts DESC')}"
        
        # 分页
        limit = filters.get('limit', 100)
        offset = filters.get('offset', 0)
        query += f" LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor = self.conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
```

---

## 5. 循环写入模式

### 5.1 JSONL 循环写入

> 评审修复 (AGG-001): 采用"先改名→创建新文件→删除旧文件"的安全顺序，消除数据丢失窗口。

**策略**: 文件达到大小上限后：
1. 将当前文件改名为 `.rotating` 后缀（标记为正在轮转）
2. 创建新文件并验证写入成功
3. 删除最旧的已完成文件
4. 移除 `.rotating` 后缀

```python
class CircularJSONLBackend(JSONLBackend):
    def __init__(self, file_path, max_files=10, max_size_mb=500):
        super().__init__(file_path)
        self.max_files = max_files
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._recover_from_interrupted_rotation()
    
    def write(self, entry):
        if self.file_path.stat().st_size > self.max_size_bytes:
            self._safe_rotate()
        super().write(entry)
    
    def _safe_rotate(self):
        """安全轮转: 先改名→创建新文件→删除旧文件"""
        import time
        
        # Step 1: 将当前文件标记为正在轮转 (改名加 .rotating 后缀)
        rotating_path = self.file_path.with_suffix('.jsonl.rotating')
        self.file_path.rename(rotating_path)
        
        try:
            # Step 2: 创建新文件并验证可写入
            new_path = self._generate_next_filename()
            with open(new_path, 'w') as f:
                f.write('')  # 验证可创建
            self.file_path = new_path
            # 重新写入全局上下文
            self._write_global_context()
            
            # Step 3: 删除最旧的已完成文件 (不超过 max_files)
            files = sorted(self._get_completed_files())
            while len(files) >= self.max_files:
                files[0].unlink()
                # 同步清理对应的 .tracebacks 文件
                tb_file = files[0].with_suffix('.tracebacks')
                if tb_file.exists():
                    tb_file.unlink()
                files = sorted(self._get_completed_files())
            
            # Step 4: 移除 .rotating 后缀 (轮转完成)
            rotating_path.rename(rotating_path.with_suffix('.jsonl'))
            
        except OSError as e:
            # 新文件创建失败 → 回滚：恢复原文件名
            rotating_path.rename(self.file_path)
            raise RuntimeError(f"Rotation failed, original file restored: {e}")
    
    def _recover_from_interrupted_rotation(self):
        """恢复被中断的轮转"""
        for f in self.file_path.parent.glob("*.rotating"):
            # 存在 .rotating 文件说明上次轮转未完成
            original = f.with_suffix('.jsonl')
            if not original.exists():
                f.rename(original)  # 恢复原文件名
            else:
                f.unlink()  # 原文件已存在，删除残留
    
    def _get_completed_files(self):
        """获取所有已完成轮转的文件 (不含 .rotating)"""
        pattern = self._extract_base_pattern(self.file_path) + "*.jsonl"
        return [f for f in self.file_path.parent.glob(pattern) 
                if not f.name.endswith('.rotating')]
```

### 5.2 SQLite 循环写入

> 评审修复 (AGG-001): 基于时间窗口的清理策略，配合定期 WAL checkpoint。

**策略**: 记录超过保留时间后删除，定期执行 WAL checkpoint 控制文件大小。

```python
class CircularSQLiteBackend(SQLiteBackend):
    def __init__(self, file_path, retention_hours=24, max_size_mb=500, checkpoint_every=1000):
        super().__init__(file_path, wal_mode=True)
        self.retention_seconds = retention_hours * 3600
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._write_count = 0
        self._checkpoint_every = checkpoint_every
    
    def write(self, entry):
        super().write(entry)
        self._write_count += 1
        
        # 每 N 次写入执行 passive checkpoint (不阻塞读写)
        if self._write_count % self._checkpoint_every == 0:
            self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        
        # 每 100 次检查一次清理条件 (避免每次写入都扫描)
        if self._write_count % 100 == 0:
            self._cleanup_if_needed()
    
    def _cleanup_if_needed(self):
        """按需清理"""
        # 条件 1: 超过保留时间的记录
        self.conn.execute(
            "DELETE FROM logs WHERE ts < datetime('now', ?)",
            (f"-{self.retention_seconds} seconds",)
        )
        
        # 条件 2: 文件大小超限 → 删除最旧 10% 的记录
        if self.file_path.stat().st_size > self.max_size_bytes:
            count = self.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            delete_count = max(count // 10, 1)
            self.conn.execute(
                "DELETE FROM logs WHERE id IN (SELECT id FROM logs ORDER BY ts ASC LIMIT ?)",
                (delete_count,)
            )
            # TRUNCATE checkpoint 释放 WAL 空间
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        
        # 同步清理孤儿 traceback
        self.conn.execute(
            "DELETE FROM tracebacks WHERE tid NOT IN (SELECT DISTINCT tid FROM logs WHERE tid IS NOT NULL)"
        )
        
        self.conn.commit()
```

---

## 6. 堆栈跟踪存储

### 6.1 分离存储策略

堆栈跟踪文本较大，单独存储在 `.tracebacks` 表/文件中，主日志只存 `tid` 引用。

**JSONL 模式**: 存储在 `{logfile}.tracebacks` 文件中
```
trace_001|ValueError|invalid literal|Traceback (most recent call last)...
trace_002|KeyError|'missing_key'|Traceback (most recent call last)...
```

**SQLite 模式**: 存储在 `tracebacks` 表中
```sql
CREATE TABLE tracebacks (
    tid TEXT PRIMARY KEY,
    traceback TEXT NOT NULL,
    exception_type TEXT,
    exception_msg TEXT
);
```

### 6.2 查询堆栈跟踪

```python
def get_traceback(tid):
    """按 tid 查询堆栈跟踪"""
    if backend_type == "sqlite":
        row = conn.execute(
            "SELECT * FROM tracebacks WHERE tid = ?", (tid,)
        ).fetchone()
        return dict(row) if row else None
    else:
        # JSONL 模式: 从 .tracebacks 文件读取
        with open(f"{file_path}.tracebacks", 'r') as f:
            for line in f:
                parts = line.strip().split('|', 3)
                if parts[0] == tid:
                    return {
                        "tid": parts[0],
                        "exception_type": parts[1],
                        "exception_msg": parts[2],
                        "traceback": parts[3]
                    }
        return None
```

---

## 7. 存储配置

### 7.1 配置文件

```yaml
# agentic_logger.yaml
storage:
  # 基础配置
  log_dir: ./logs
  program: my_agent
  command: main
  
  # 后端选择
  backend: auto           # jsonl | sqlite | auto
  auto_threshold_mb: 100  # auto 模式下的阈值
  
  # JSONL 配置
  jsonl:
    compress_after_days: 1
  
  # SQLite 配置
  sqlite:
    wal_mode: true
    busy_timeout_ms: 5000
    synchronous: NORMAL
  
  # 循环写入
  circular:
    enabled: false
    max_size_mb: 500        # 最大文件大小
    max_files: 10           # JSONL: 最大文件数
    retention_count: 100000 # SQLite: 最大记录数
  
  # 堆栈跟踪
  traceback:
    separate_storage: true  # 分离存储
```

### 7.2 动态配置

```python
from agentic_logger import configure

configure(
    storage="auto",
    auto_threshold_mb=100,
    circular=True,
    max_size_mb=500,
    retention_count=100000,
)
```

---

## 8. 备份与恢复

### 8.1 JSONL 备份

```bash
# 备份
cp logs/*.jsonl backup/
cp logs/*.tracebacks backup/

# 压缩
gzip logs/*.jsonl
```

### 8.2 SQLite 备份

```bash
# 在线备份 (不影响写入)
sqlite3 logs/my_agent_main_2026-07-21_103000.sqlite ".backup 'backup/my_agent_backup.sqlite'"

# 恢复
cp backup/my_agent_backup.sqlite logs/
```
