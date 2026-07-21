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

**策略**: 文件达到大小上限后，创建新文件，删除最旧的文件。

```python
class CircularJSONLBackend(JSONLBackend):
    def __init__(self, file_path, max_files=10, max_size_mb=500):
        super().__init__(file_path)
        self.max_files = max_files
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._base_pattern = self._extract_base_pattern(file_path)
    
    def write(self, entry):
        if self.file_path.stat().st_size > self.max_size_bytes:
            self._rotate()
        super().write(entry)
    
    def _rotate(self):
        """轮转: 删除最旧，创建新文件"""
        files = sorted(self._get_log_files())
        
        # 删除最旧的文件
        if len(files) >= self.max_files:
            files[0].unlink()
        
        # 创建新文件 (时间戳递增)
        now = datetime.now()
        new_name = f"{self._base_pattern}_{now.strftime('%H%M%S')}.jsonl"
        self.file_path = self.file_path.parent / new_name
    
    def _get_log_files(self):
        """获取同组的所有日志文件"""
        pattern = self._base_pattern + "*.jsonl"
        return list(self.file_path.parent.glob(pattern))
```

### 5.2 SQLite 循环写入

**策略**: 记录数达到上限后，删除最旧的记录。

```python
class CircularSQLiteBackend(SQLiteBackend):
    def __init__(self, file_path, retention_count=100000, max_size_mb=None):
        super().__init__(file_path, wal_mode=True)
        self.retention_count = retention_count
        self.max_size_bytes = (max_size_mb or 500) * 1024 * 1024
    
    def write(self, entry):
        super().write(entry)
        
        # 检查是否需要清理
        count = self._count()
        if count > self.retention_count:
            self._delete_oldest(count - self.retention_count)
        
        # 检查文件大小
        size = self.file_path.stat().st_size
        if size > self.max_size_bytes:
            self._vacuum_and_cleanup()
    
    def _delete_oldest(self, count):
        """删除最旧的 N 条记录"""
        self.conn.execute(
            "DELETE FROM logs WHERE id IN (SELECT id FROM logs ORDER BY ts ASC LIMIT ?)",
            (count,)
        )
        self.conn.commit()
    
    def _vacuum_and_cleanup(self):
        """压缩数据库"""
        self.conn.execute("VACUUM")
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
