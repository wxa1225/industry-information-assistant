# 故障排查记录

## 2026-03-24: 前端报错 "Request failed with status code 404"

### 问题现象
- 前端 UI 界面报错 "Request failed with status code 404"
- 创建账户时弹窗报错
- 所有 `/auth/*` 端点返回 404

### 根本原因
**端口冲突：8000 端口被多个进程占用**

- Docker 容器（PID 20600）占用 8000 端口
- Python 后端服务（PID 11060）也尝试占用 8000 端口
- 导致请求被路由到错误的服务，返回 404

### 解决方案
停止 Docker 容器或更改后端服务端口，确保只有一个服务监听 8000 端口

### 排查过程中的错误尝试
1. ❌ 修改 `oauth2_scheme` 的 `tokenUrl` 参数 - 这不是问题所在
2. ❌ 检查路由注册 - 路由配置正确
3. ❌ 重启后端服务 - 端口冲突导致重启无效

### 经验教训
- 遇到 404 错误时，首先检查端口是否被多个进程占用
- 使用 `netstat -ano | findstr ":端口号"` 检查端口占用情况
- Docker 容器可能会占用常用端口，需要注意冲突

---

## 2026-03-24: 知识库文档上传失败

### 问题现象
- 在知识库提交文档时显示"文档提交失败"
- 后台错误：`PermissionError: [WinError 32] 另一个程序正在使用此文件，进程无法访问`

### 根本原因
**三个问题：**

1. **Windows 路径兼容性问题**
   - `UPLOAD_DIR = "/tmp/knowledge_uploads"` - Linux 路径，Windows 不支持

2. **上传文件句柄未关闭**
   - 上传的文件保存后，`file.file` 句柄未关闭
   - 导致后续处理时文件被占用

3. **处理完成后立即删除文件**
   - `process_document` 函数在处理完成后立即删除临时文件
   - 但 DocMind 服务可能还在使用文件，导致删除失败

### 解决方案

1. 修改为跨平台路径：
```python
UPLOAD_DIR = os.path.join(os.getcwd(), "uploads", "knowledge")
```

2. 保存后关闭文件句柄：
```python
with open(file_path, "wb") as buffer:
    shutil.copyfileobj(file.file, buffer)
await file.close()  # 关闭上传的文件句柄
```

3. 删除文件时添加重试机制：
```python
for i in range(3):
    try:
        os.remove(file_path)
        break
    except PermissionError:
        if i < 2:
            time.sleep(1)
        else:
            pass  # 最后一次失败就放弃
```

### 修复文件
- `backend/app/router/knowledge_router.py:28` - 路径修复
- `backend/app/router/knowledge_router.py:331` - 添加文件关闭
- `backend/app/router/knowledge_router.py:120` - 添加删除重试

### 经验教训
- 使用 `os.path.join()` 而非硬编码路径
- 避免使用 Linux 特定路径如 `/tmp`
- **上传文件处理完后必须关闭句柄**
- **删除文件前确保没有其他进程在使用**
- Windows 文件锁定比 Linux 更严格，需要添加重试机制



