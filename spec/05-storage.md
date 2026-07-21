# 05 - 存储后端设计

## 1. 概述

AgenticLogger 支持多种存储后端，按优先级分阶段实现。

| 后端 | 优先级 | 用途 | 特点 |
|------|--------|------|------|
| **JSONL** | P0 | 默认 | 流式、简单、可 grep |
| **SQLite** | P1 | 可选 | 索引快、单文件 |
| **PostgreSQL** | P2 | 未来 | 大规模、多用户 |

---

## 2. JSONL 后端 (默认)

### 2.1 文件组织

```
logs/
├── agentic-2026-07-21.jsonl          # 当天日志
├── agentic-2026-07-20.jsonl.gz       # 昨天(压缩)
├── agentic-2026-07-19.jsonl.gz       # 前天(压缩)
├── ...
└── archive/                          # 归档目录
    └── 2026/
        └── 06/
            └── agentic-2026-06-30.jsonl.gz
```

### 2.2 文件命名

**格式**: `agentic-{YYYY-MM-DD}.jsonl`

**轮转**: 每天 00:00 自动轮转

**压缩**: 次日自动 gzip 压缩

**保留**: 默认保留 30 天

### 2.3 写入流程

```python
class JSONLBackend:
    def __init__(self, log_dir="./logs"):
        self.log_dir = Path(log_dir)
        self.current_file = None
        self.current_date = None
    
    def write(self, log_entry: dict):
        """写入单条日志"""
        date = datetime.now().date()
        
        # 日期变更时轮转
        if date != self.current_date:
            self._rotate(date)
        
        # 追加写入
        line = json.dumps(log_entry, ensure_ascii=False)
        with open(self.current_file, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    
    def _rotate(self, new_date):
        """日志轮转"""
        # 压缩旧文件
        if self.current_file and self.current_file.exists():
            gzip_file(self.current_file)
        
        # 创建新文件
        self.current_date = new_date
        self.current_file = self.log_dir / f"agentic-{new_date}.jsonl"
```

### 2.4 读取流程

```python
class JSONLReader:
    def __init__(self, log_dir="./logs"):
        self.log_dir = Path(log_dir)
    
    def query(self, level=None, since=None, limit=100):
        """查询日志"""
        results = []
        
        # 确定要读取的文件
        files = self._get_files(since)
        
        for file in files:
            with open(file, 'r', encoding='utf-8') as f:
                for line in f:
                    entry = json.loads(line)
                    
                    # 过滤
                    if level and entry.get('level') != level:
                        continue
                    if since and entry.get('ts') < since:
                        continue
                    
                    results.append(entry)
                    
                    if len(results) >= limit:
                        return results
        
        return results
    
    def stream(self, level=None):
        """实时流"""
        current_file = self._get_current_file()
        
        with open(current_file, 'r', encoding='utf-8') as f:
            # 移到文件末尾
            f.seek(0, 2)
            
            while True:
                line = f.readline()
                if line:
                    entry = json.loads(line)
                    if not level or entry.get('level') == level:
                        yield entry
                else:
                    time.sleep(0.1)
```

### 2.5 性能优化

**批量写入**:
```python
def write_batch(self, entries: list[dict]):
    """批量写入"""
    lines = [json.dumps(e, ensure_ascii=False) for e in entries]
    with open(self.current_file, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
```

**缓冲写入**:
```python
class BufferedJSONLBackend:
    def __init__(self, buffer_size=100):
        self.buffer = []
        self.buffer_size = buffer_size
    
    def write(self, entry):
        self.buffer.append(entry)
        if len(self.buffer) >= self.buffer_size:
            self._flush()
    
    def _flush(self):
        """刷新缓冲区"""
        if self.buffer:
            self._write_batch(self.buffer)
            self.buffer = []
```

### 2.6 压缩与归档

```python
import gzip
import shutil

def compress_file(file_path: Path):
    """压缩文件"""
    with open(file_path, 'rb') as f_in:
        with gzip.open(f"{file_path}.gz", 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    file_path.unlink()

def cleanup_old_files(log_dir: Path, days=30):
    """清理旧文件"""
    cutoff = datetime.now() - timedelta(days=days)
    for file in log_dir.glob("agentic-*.jsonl.gz"):
        date = parse_date_from_filename(file)
        if date < cutoff:
            file.unlink()
```

---

## 3. SQLite 后端 (可选)

### 3.1 数据库 Schema

```sql
-- 主表：日志条目
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,           -- ISO 8601 timestamp
    level TEXT NOT NULL,        -- INFO, WARN, ERROR, TOOL, ...
    msg TEXT NOT NULL,          -- 日志消息
    module TEXT,                -- 模块名
    context TEXT,               -- JSON 格式的上下文
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_logs_ts ON logs(ts);
CREATE INDEX idx_logs_level ON logs(level);
CREATE INDEX idx_logs_module ON logs(module);
CREATE INDEX idx_logs_ts_level ON logs(ts, level);

-- 全文索引 (可选)
CREATE VIRTUAL TABLE logs_fts USING fts5(msg, context, content=logs, content_rowid=id);
```

### 3.2 写入流程

```python
import sqlite3

class SQLiteBackend:
    def __init__(self, db_path="./logs/agentic.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                level TEXT NOT NULL,
                msg TEXT NOT NULL,
                module TEXT,
                context TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
            CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
        """)
    
    def write(self, entry: dict):
        """写入单条日志"""
        context = json.dumps(entry.get('context', {}), ensure_ascii=False)
        self.conn.execute(
            "INSERT INTO logs (ts, level, msg, module, context) VALUES (?, ?, ?, ?, ?)",
            (entry['ts'], entry['level'], entry['msg'], entry.get('module'), context)
        )
        self.conn.commit()
    
    def query(self, level=None, since=None, limit=100):
        """查询日志"""
        query = "SELECT * FROM logs WHERE 1=1"
        params = []
        
        if level:
            query += " AND level = ?"
            params.append(level)
        
        if since:
            query += " AND ts >= ?"
            params.append(since)
        
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        
        cursor = self.conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
```

### 3.3 性能对比

| 操作 | JSONL | SQLite |
|------|-------|--------|
| 写入 | ~0.1ms | ~1ms |
| 查询(1000行) | ~500ms | ~50ms |
| 实时流 | ✅ 支持 | ⚠️ 需要轮询 |
| 文件大小 | 大(无索引) | 小(有索引) |
| 并发写入 | ⚠️ 需锁 | ✅ 支持 |

### 3.4 适用场景

**JSONL 适合**:
- 实时流处理
- 简单部署
- 日志量 < 1GB/天

**SQLite 适合**:
- 频繁查询
- 需要索引
- 日志量 < 10GB

---

## 4. PostgreSQL 后端 (未来)

### 4.1 Schema

```sql
CREATE TABLE logs (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    level VARCHAR(20) NOT NULL,
    msg TEXT NOT NULL,
    module VARCHAR(100),
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 分区表 (按月)
CREATE TABLE logs_2026_07 PARTITION OF logs
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');

-- 索引
CREATE INDEX idx_logs_ts ON logs(ts DESC);
CREATE INDEX idx_logs_level ON logs(level);
CREATE INDEX idx_logs_context ON logs USING GIN(context);
```

### 4.2 适用场景

- 大规模部署 (> 100GB)
- 多用户并发
- 复杂查询需求
- 需要数据仓库集成

---

## 5. 存储配置

### 5.1 配置文件

```yaml
# agentic_logger.yaml
storage:
  backend: jsonl          # jsonl | sqlite | postgresql
  log_dir: ./logs         # JSONL 目录
  db_path: ./logs/agentic.db  # SQLite 路径
  
  # 轮转策略
  rotation:
    enabled: true
    schedule: daily       # daily | hourly | size
    max_size: 1GB         # size 轮转时
    compress: true
    retention_days: 30
  
  # 性能配置
  buffer_size: 100        # 缓冲区大小
  flush_interval: 5s      # 刷新间隔
```

### 5.2 动态切换

```python
from agentic_logger import configure

# 使用 JSONL
configure(storage_backend="jsonl", log_dir="./logs")

# 使用 SQLite
configure(storage_backend="sqlite", db_path="./logs/agentic.db")
```

---

## 6. 备份与恢复

### 6.1 JSONL 备份

```bash
# 备份
tar -czf logs-backup-2026-07-21.tar.gz logs/

# 恢复
tar -xzf logs-backup-2026-07-21.tar.gz
```

### 6.2 SQLite 备份

```bash
# 在线备份
sqlite3 logs/agentic.db ".backup 'logs/agentic-backup.db'"

# 恢复
cp logs/agentic-backup.db logs/agentic.db
```

---

## 7. 监控与维护

### 7.1 磁盘空间监控

```python
def check_disk_space(log_dir, threshold_gb=10):
    """检查磁盘空间"""
    usage = shutil.disk_usage(log_dir)
    free_gb = usage.free / (1024**3)
    if free_gb < threshold_gb:
        cleanup_old_files(log_dir, days=7)  # 紧急清理
```

### 7.2 日志健康检查

```bash
# CLI 命令
agentic-logger health

# 输出
Storage Health:
  Backend: JSONL
  Total files: 30
  Total size: 2.3 GB
  Free space: 45.2 GB
  Oldest log: 2026-06-21
  Latest log: 2026-07-21
  Status: ✅ Healthy
```
