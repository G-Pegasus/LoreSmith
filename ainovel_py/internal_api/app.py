# 兼容旧版 Python 的类型注解语法（固定写法，无需关注）
from __future__ import annotations

# FastAPI 核心：应用对象、跨域中间件
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ===================== 导入项目内部模块 =====================
# 数据持久化存储（相当于 Java 的 Repository / DAO）
from ainovel_py.internal_api.persistence import RunRegistryStore, RunTaskStore
# 运行时注册中心（相当于 Java 的 Manager / Registry 管理类）
from ainovel_py.internal_api.registry import RunRegistry
# 路由 + 全局异常处理器
from ainovel_py.internal_api.routes import install_error_handlers, router
# 业务服务（相当于 Java @Service）
from ainovel_py.internal_api.service import RunService
# 工作空间相关路由、服务
from ainovel_py.internal_api.workspace_routes import router as workspace_router
from ainovel_py.internal_api.workspace_service import WorkspaceService
# 配置加载（你上一段看的配置类）
from ainovel_py.internal_api.settings import load_settings
# 后台工作进程（相当于 Java @Async 线程池）
from ainovel_py.internal_api.worker import WorkerManager

# ===================== FastAPI 应用工厂函数 =====================
# 作用：创建并初始化整个 FastAPI 应用
# 等价于 Java SpringBoot 的启动类 + 自动配置类
def create_app() -> FastAPI:
    # 1. 创建 FastAPI 应用实例
    # 等价 Java：new SpringApplication()
    app = FastAPI(
        title="ainovel internal api",        # API 文档标题
        version="0.1.0",                     # 版本
        description="Internal API consumed by the Java platform layer to control and observe the Python agent runtime.",
    )

    # 2. 加载配置（读取环境变量 + 默认值）
    # 等价 Java：@Autowired 注入配置类
    settings = load_settings()

    # 3. 添加跨域中间件（解决前端访问跨域问题）
    # 等价 Java：@CrossOrigin / 配置 CORSFilter
    app.add_middleware(
        CORSMiddleware,
        # 允许访问的前端地址（localhost:5173是前端默认端口，8080是Java后端端口）
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:174",
            "http://127.0.0.1:8080",
            "http://localhost:8080",
        ],
        allow_credentials=True,   # 允许携带Cookie
        allow_methods=["*"],      # 允许所有HTTP方法
        allow_headers=["*"],      # 允许所有请求头
    )

    # 4. 初始化数据存储（文件持久化，相当于数据库）
    # RunRegistryStore：存储运行任务主数据
    # RunTaskStore：存储子任务数据
    store = RunRegistryStore(settings.registry_path)
    task_store = RunTaskStore(settings.registry_path + ".tasks")

    # 5. 创建任务注册中心，并从文件恢复历史数据
    # 等价 Java：@PostConstruct 初始化数据
    registry = RunRegistry(store, task_store)
    registry.restore()  # 重启服务后恢复之前的任务状态

    # 6. 初始化并启动后台工作进程
    # 作用：在后台自动执行小说生成任务
    # 等价 Java：@Async 或 单独启动一个线程池
    worker = WorkerManager(registry)
    worker.start()

    # 7. 将所有核心组件挂载到 FastAPI 全局状态 app.state
    # 等价 Java：把 Bean 放入 Spring ApplicationContext 容器
    app.state.settings = settings          # 配置
    app.state.run_registry = registry      # 任务注册中心
    app.state.run_service = RunService(registry)        # 运行服务
    app.state.workspace_service = WorkspaceService()     # 工作空间服务
    app.state.worker_manager = worker      # 后台任务管理器

    # 8. 注册路由（加载所有API接口）
    # 等价 Java：@RestController 注册控制器
    app.include_router(router)                     # 核心业务接口
    app.include_router(workspace_router)           # 工作空间接口

    # 9. 安装全局异常处理器
    # 等价 Java：@RestControllerAdvice 全局异常处理
    install_error_handlers(app)

    # 10. 返回配置完成的 FastAPI 应用
    return app

# ===================== 应用启动入口 =====================
# 调用工厂方法，创建最终可运行的 app 实例
app = create_app()