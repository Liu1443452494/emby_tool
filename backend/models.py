from pydantic import BaseModel, Field
from typing import Literal, List, Optional, Dict, Any

# --- 基础配置模型 ---

class ProxyRule(BaseModel):
    """单条自定义代理规则"""
    enabled: bool = Field(default=True, description="是否启用此规则")
    remark: str = Field(default="", description="规则备注")
    keyword: str = Field(default="", description="用于匹配URL的关键词")

class ProxyConfig(BaseModel):
    """HTTP 代理配置"""
    enabled: bool = Field(default=False, description="是否启用代理")
    url: str = Field(default="", description="代理服务器URL")
    
    mode: Literal['whitelist', 'blacklist'] = Field(default='blacklist', description="代理模式：whitelist-仅代理勾选的, blacklist-代理所有但排除勾选的")
    
    # 内置规则的启用状态
    target_tmdb: bool = Field(default=False, description="内置规则：TMDB")
    target_douban: bool = Field(default=True, description="内置规则：豆瓣")
    target_emby: bool = Field(default=True, description="内置规则：Emby")
    
    # 自定义规则列表
    custom_rules: List[ProxyRule] = Field(default_factory=list, description="用户自定义代理规则列表")
    
    # 高级排除列表
    exclude: str = Field(default="", description="代理排除列表，逗号分隔 (高级)")

DownloadBehavior = Literal["skip", "overwrite"]

class ServerConfig(BaseModel):
    """Emby 服务器连接配置"""
    server: str = ""
    api_key: str = ""
    user_id: str = ""

class DownloadConfig(BaseModel):
    """文件下载相关配置"""
    download_directory: str = ""
    download_behavior: DownloadBehavior = "skip"
    directory_naming_rule: Literal["tmdb_id", "media_path"] = Field(
        default="tmdb_id", 
        description="下载目录命名规则"
    )
    nfo_actor_limit: int = Field(default=20, description="写入NFO文件中的最大演员数量")

class TmdbConfig(BaseModel):
    """TMDB API 配置"""
    api_key: str = ""
    custom_api_domain_enabled: bool = Field(default=False, description="是否启用自定义API域名")
    custom_api_domain: str = Field(default="https://api.themoviedb.org", description="自定义TMDB API域名")

class DoubanConfig(BaseModel):
    """豆瓣数据源配置"""
    directory: str = ""
    refresh_cron: str = ""
    extra_fields: List[str] = Field(default_factory=list)

class DoubanCacheStatus(BaseModel):
    """豆瓣缓存状态信息，用于前端展示"""
    exists: bool
    item_count: int
    last_modified: Optional[str] = None
    is_scanning: bool

class TencentApiConfig(BaseModel):
    """腾讯云翻译 API 配置"""
    secret_id: str = ""
    secret_key: str = ""
    region: str = "ap-guangzhou"

class SiliconflowApiConfig(BaseModel):
    """SiliconFlow 大模型 API 配置"""
    api_key: str = ""
    model_name: str = "Qwen/Qwen2-7B-Instruct"
    model_remarks: Dict[str, str] = Field(default_factory=dict)

    temperature: float = Field(
        default=0.0, 
        description="温度，控制生成文本的随机性。0.0 表示最确定性的输出。",
        ge=0.0,
        le=2.0
    )
    top_p: float = Field(
        default=1.0,
        description="核心采样，控制生成文本的多样性。1.0 表示不进行核心采样。",
        ge=0.0,
        le=1.0
    )
    timeout_single: int = Field(
        default=20,
        description="单个翻译的API请求超时时间（秒）。",
        ge=5,
        le=120
    )
    timeout_batch: int = Field(
        default=45,
        description="批量翻译的API请求超时时间（秒）。",
        ge=10,
        le=300
    )
    batch_translation_enabled: bool = Field(
        default=True,
        description="是否启用批量翻译模式，可大幅减少API请求次数"
    )

class ActorLocalizerConfig(BaseModel):
    """演员中文化功能的完整配置"""
    replace_english_role: bool = False
    enhance_english_role_with_douban: bool = Field(default=True, description="是否用豆瓣更丰富的英文角色名优化已有的英文角色名")
    translation_enabled: bool = False
    translation_mode: Literal["translators", "tencent", "siliconflow"] = "translators"
    translator_engine: str = "baidu"
    api_cooldown_enabled: bool = True
    api_cooldown_time: float = 0.2
    person_limit: int = 15
    ignore_generic_douban_roles: bool = Field(default=False, description="是否忽略豆瓣中的通用角色名，如'演员'、'配音'等")
    generic_role_blacklist: List[str] = Field(
        default_factory=lambda: ["演员"], 
        description="要忽略的通用角色名列表"
    )
    tencent_config: TencentApiConfig = Field(default_factory=TencentApiConfig)
    siliconflow_config: SiliconflowApiConfig = Field(default_factory=SiliconflowApiConfig)
    apply_cron: str = Field(default="", description="定时自动应用CRON表达式")

class DoubanFixerConfig(BaseModel):
    """豆瓣ID修复器配置"""
    cookie: str = Field(default="", description="豆瓣用户Cookie")
    api_cooldown: float = Field(default=2.0, description="API请求冷却时间（秒）")
    scan_cron: str = Field(default="", description="定时扫描CRON表达式")

class DoubanPosterUpdaterConfig(BaseModel):
    """豆瓣海报更新器功能的配置"""
    update_interval: float = Field(default=1.0, description="处理每个媒体的间隔时间（秒）")
    overwrite_existing: bool = Field(default=False, description="是否覆盖已有海报")
    skip_mainland_china: bool = Field(default=False, description="是否跳过中国大陆地区的影视")



class GitHubCacheConfig(BaseModel):
    """GitHub 远程图床缓存配置"""
    repo_url: str = Field(default="", description="GitHub 仓库 URL, 例如: https://github.com/user/repo")
    branch: str = Field(default="main", description="仓库分支")
    personal_access_token: str = Field(default="", description="个人访问令牌 (PAT)，用于写入权限")
    allow_fallback: bool = Field(default=True, description="远程图床找不到时，是否允许降级为实时截图")
    overwrite_remote: bool = Field(default=False, description="备份时，是否覆盖远程已存在的同名文件")
    download_cooldown: float = Field(default=0.5, description="从GitHub下载文件（如索引）前的冷却时间（秒）", ge=0)
    upload_cooldown: float = Field(default=1.0, description="向GitHub上传文件（截图或索引）前的冷却时间（秒）", ge=0)
    delete_cooldown: float = Field(default=1.5, description="从GitHub删除文件前的冷却时间（秒）", ge=0)

class EpisodeRefresherConfig(BaseModel):
    """剧集元数据刷新器功能的配置"""
    refresh_mode: Literal['emby', 'toolbox'] = Field(
        default='emby', 
        description="刷新模式: 'emby' - 通知Emby刷新, 'toolbox' - 工具箱代理刷新"
    )
    overwrite_metadata: bool = Field(default=True, description="刷新时是否覆盖现有元数据 (仅emby模式)")
    skip_if_complete: bool = Field(default=True, description="如果分集已有标题、简介和图片，则跳过刷新")
    
    screenshot_enabled: bool = Field(
        default=False,
        description="当TMDB和Emby均无图片时，是否尝试从视频文件截图"
    )
    
    # 新增：截图缓存模式
    screenshot_cache_mode: Literal['none', 'local', 'remote'] = Field(
        default='local',
        description="截图与缓存模式: 'none'-无缓存, 'local'-本地缓存, 'remote'-远程图床"
    )
    # 兼容旧版，后续在 config.py 中迁移
    local_screenshot_caching_enabled: Optional[bool] = Field(
        default=None, 
        description="[已废弃] 是否启用本地截图缓存"
    )

    screenshot_percentage: int = Field(
        default=10,
        description="截图位置在视频时长的百分比 (1-99)",
        ge=1,
        le=99
    )
    screenshot_fallback_seconds: int = Field(
        default=150,
        description="获取视频时长失败时的保底截图秒数",
        ge=1
    )
    
    crop_widescreen_to_16_9: bool = Field(
        default=True,
        description="是否将宽屏(如21:9)截图裁剪为16:9以适应Emby显示"
    )
    force_overwrite_screenshots: bool = Field(
        default=False,
        description="是否强制覆盖已存在的截图(用于调整参数后重新截图)"
    )

    screenshot_cooldown: float = Field(
        default=2.0,
        description="每次截图操作之间的等待时间(秒)，用于保护视频源服务器",
        ge=0
    )
    use_smart_screenshot: bool = Field(
        default=True,
        description="是否启用智能截图(分析1秒内多帧选择最清晰的一张)，会增加CPU消耗"
    )

    backup_overwrite_local: bool = Field(
        default=False,
        description="从Emby备份截图到本地时，是否覆盖本地已有的同名文件"
    )
    
    # 新增：GitHub 配置
    github_config: GitHubCacheConfig = Field(default_factory=GitHubCacheConfig)

# --- 核心修改结束 ---


class EpisodeRenamerConfig(BaseModel):
    """剧集文件重命名器功能的配置"""
    emby_path_root: str = Field(default="/media", description="Emby 容器内看到的媒体根路径")
    clouddrive_path_root: str = Field(default="/cd2", description="CloudDrive 挂载到本工具容器内的根路径")
    clouddrive_rename_cooldown: float = Field(default=1.0, description="每次重命名网盘文件之间的间隔时间（秒）", ge=0)


class GitHubRepoState(BaseModel):
    """记录单个GitHub仓库的状态"""
    # --- 修改 ---
    size_bytes: int = Field(default=0, description="该仓库已用空间大小，单位Bytes")
    # --- 修改结束 ---
    last_checked: str = Field(default="", description="上次更新此状态的ISO 8601格式时间戳")

class GitHubRepo(BaseModel):
    """单个GitHub仓库的配置"""
    repo_url: str = Field(..., description="仓库的HTTPS URL")
    branch: str = Field(default="main", description="操作的目标分支名称")
    personal_access_token: str = Field(default="", description="仓库级的PAT，覆盖全局PAT")
    state: GitHubRepoState = Field(default_factory=GitHubRepoState)

class PosterManagerConfig(BaseModel):
    """海报管理器功能的完整配置"""
    local_cache_path: str = Field(default="", description="本地图片缓存的根目录")
    global_personal_access_token: str = Field(default="", description="全局GitHub PAT")
    repository_size_threshold_mb: int = Field(default=900, description="单个仓库的容量上限阈值 (MB)")
    image_download_cooldown_seconds: float = Field(default=0.5, description="从GitHub下载图片文件前的等待时间 (秒)")
    file_upload_cooldown_seconds: float = Field(default=1.0, description="向GitHub上传文件（图片或索引）前的等待时间 (秒)")
    overwrite_remote_files: bool = Field(default=False, description="全局开关，决定备份时是否覆盖GitHub上已存在的同名文件")
    overwrite_on_restore: bool = Field(default=False, description="全局开关，决定恢复时是否覆盖Emby上已存在的图片")
    restore_mode: Literal['standard', 'from_remote'] = Field(default='standard', description="恢复模式: 'standard' - 标准模式, 'from_remote' - 从远程备份反向恢复")
    github_repos: List[GitHubRepo] = Field(default_factory=list, description="仓库列表，顺序即代表优先级")
# --- 结束新增 ---
    

class ScheduledTaskItem(BaseModel):
    """单个定时任务的配置"""
    id: str
    name: str
    enabled: bool = False
    cron: str = ""
    hasSettings: bool = Field(default=True, description="前端是否显示此任务的独立设置按钮")

class ScheduledTasksTargetScope(BaseModel):
    """定时任务通用的目标范围配置"""
    mode: Literal['latest', 'all', 'by_type', 'by_library', 'by_search', 'favorites'] = 'latest'
    days: int = 7
    limit: int = 100
    media_type: Optional[Literal["Movie", "Series"]] = "Movie"
    library_ids: List[str] = Field(default_factory=list)
    library_blacklist: str = ""
    item_ids: List[str] = Field(default_factory=list)

class ScheduledTasksConfig(BaseModel):
    """定时任务总配置"""
    target_scope: ScheduledTasksTargetScope = Field(default_factory=ScheduledTasksTargetScope)
    tasks: List[ScheduledTaskItem] = Field(default_factory=lambda: [
        ScheduledTaskItem(id="actor_localizer", name="演员中文化"),
        ScheduledTaskItem(id="douban_fixer", name="豆瓣ID修复器"),
        ScheduledTaskItem(id="douban_poster_updater", name="豆瓣海报更新"),
        ScheduledTaskItem(id="episode_refresher", name="剧集元数据刷新"),
        ScheduledTaskItem(id="episode_renamer", name="剧集文件重命名", hasSettings=True),
        ScheduledTaskItem(id="id_mapper", name="TMDB-Emby ID 映射表", hasSettings=False),
        ScheduledTaskItem(id="actor_role_mapper", name="演员角色映射", hasSettings=True)
    ])

class WebhookConfig(BaseModel):
    """Webhook 相关配置"""
    enabled: bool = Field(default=False, description="是否启用 Webhook 自动处理")
    url_override: str = Field(default="", description="用户自定义的 Webhook URL，如果为空，则前端会显示一个推荐值")
    initial_wait_time: int = Field(default=30, description="收到通知后，等待 Emby 刮削的初始时间（秒）")
    plugin_wait_time: int = Field(default=60, description="ID修复后，等待豆瓣插件下载数据的时间（秒）")

class TelegramConfig(BaseModel):
    """Telegram 通知配置"""
    enabled: bool = Field(default=False, description="是否启用Telegram通知")
    bot_token: str = Field(default="", description="Telegram Bot Token")
    chat_id: str = Field(default="", description="接收通知的Chat ID")

class TraktConfig(BaseModel):
    """Trakt.tv API 配置"""
    enabled: bool = Field(default=False, description="是否启用 Trakt.tv 数据增强")
    client_id: str = Field(default="", description="Trakt.tv 应用的 Client ID")


class HdhiveSigninConfig(BaseModel):
    """影巢签到模块的配置"""
    enabled: bool = Field(default=False, description="是否启用此模块")
    cookie: str = Field(default="", description="站点Cookie")
    cron: str = Field(default="0 8 * * *", description="签到周期CRON表达式")
    random_delay: str = Field(default="1-300", description="随机延迟范围(秒),格式为 min-max")
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_interval: int = Field(default=30, description="重试间隔(秒)")
    history_days: int = Field(default=30, description="历史保留天数")
    send_notification: bool = Field(default=True, description="任务完成后是否发送通知")

class SigninModulesConfig(BaseModel):
    """聚合所有签到模块的配置"""
    hdhive: HdhiveSigninConfig = Field(default_factory=HdhiveSigninConfig)
    # 未来可在此处添加其他签到模块的配置
    # another_site: AnotherSiteConfig = Field(default_factory=AnotherSiteConfig)


class ChasingCenterConfig(BaseModel):
    """自动化追更中心配置"""
    enabled: bool = Field(default=False, description="是否启用自动化追更工作流")
    maintenance_cron: str = Field(default="0 3 * * *", description="每日维护任务的CRON表达式")
    notification_cron: str = Field(default="0 9 * * *", description="追剧日历通知的CRON表达式")
    calendar_days: int = Field(default=7, description="追剧日历预告未来的天数")
    completion_deadline_days: int = Field(default=30, description="完结剧集等待元数据补全的最后期限(天)")

class UpcomingFilterConfig(BaseModel):
    """即将上映功能的筛选配置"""
    fetch_days: int = Field(default=1, description="获取未来多少天的数据")
    genre_blacklist: List[str] = Field(default_factory=lambda: ['talk-show', 'reality', 'news', 'game-show', 'documentary'], description="类型黑名单")
    p0_countries: List[str] = Field(default_factory=lambda: ['cn', 'hk', 'tw'], description="P0 核心市场国家/地区列表")
    p0_languages: List[str] = Field(default_factory=lambda: ['zh'], description="P0 核心市场语言列表")
    p1_countries: List[str] = Field(default_factory=lambda: ['us', 'jp', 'gb', 'kr'], description="P1 潜力市场国家/地区列表")

class AutoSubscribeRules(BaseModel):
    """自动化订阅规则"""
    enabled: bool = Field(default=False, description="是否启用自动化订阅")
    actors: List[str] = Field(default_factory=list, description="匹配的演员关键词列表")
    min_popularity: float = Field(default=0.0, description="热门度最小阈值")
    countries: List[str] = Field(default_factory=list, description="匹配的国家/地区列表")

class UpcomingConfig(BaseModel):
    """即将上映功能的完整配置"""
    enabled: bool = Field(default=True, description="是否启用此功能")
    notification_cron: str = Field(default="0 9 * * *", description="每日订阅通知的CRON表达式")
    pruning_cron: str = Field(default="0 1 * * *", description="每日清理过期项目的CRON表达式")
    filters: UpcomingFilterConfig = Field(default_factory=UpcomingFilterConfig)
    auto_subscribe_rules: AutoSubscribeRules = Field(default_factory=AutoSubscribeRules)



class ActorRoleMapperConfig(BaseModel):
    """演员角色映射器配置"""
    actor_limit: int = Field(default=50, description="每个媒体项处理的演员数量上限", ge=1, le=200)

class AppConfig(BaseModel):
    """应用的主配置模型，聚合所有子配置"""
    server_config: ServerConfig = Field(default_factory=ServerConfig)
    download_config: DownloadConfig = Field(default_factory=DownloadConfig)
    tmdb_config: TmdbConfig = Field(default_factory=TmdbConfig)
    proxy_config: ProxyConfig = Field(default_factory=ProxyConfig)
    genre_mapping: Dict[str, str] = Field(default_factory=dict)
    douban_config: DoubanConfig = Field(default_factory=DoubanConfig)
    douban_cache_status: Optional[DoubanCacheStatus] = None
    actor_localizer_config: ActorLocalizerConfig = Field(default_factory=ActorLocalizerConfig)
    douban_fixer_config: DoubanFixerConfig = Field(default_factory=DoubanFixerConfig)
    scheduled_tasks_config: ScheduledTasksConfig = Field(default_factory=ScheduledTasksConfig)
    douban_poster_updater_config: DoubanPosterUpdaterConfig = Field(default_factory=DoubanPosterUpdaterConfig)
    webhook_config: WebhookConfig = Field(default_factory=WebhookConfig)
    episode_refresher_config: EpisodeRefresherConfig = Field(default_factory=EpisodeRefresherConfig)
    episode_renamer_config: EpisodeRenamerConfig = Field(default_factory=EpisodeRenamerConfig)
    poster_manager_config: PosterManagerConfig = Field(default_factory=PosterManagerConfig)
    telegram_config: TelegramConfig = Field(default_factory=TelegramConfig)
    trakt_config: TraktConfig = Field(default_factory=TraktConfig)
    signin_config: SigninModulesConfig = Field(default_factory=SigninModulesConfig)
    chasing_center_config: ChasingCenterConfig = Field(default_factory=ChasingCenterConfig)
    upcoming_config: UpcomingConfig = Field(default_factory=UpcomingConfig)
    actor_role_mapper_config: ActorRoleMapperConfig = Field(default_factory=ActorRoleMapperConfig)

class TargetScope(BaseModel):
    scope: Literal["media_type", "library", "all_libraries", "search"]
    media_type: Optional[Literal["Movie", "Series"]] = None
    library_ids: Optional[List[str]] = None
    library_blacklist: Optional[str] = None
    item_ids: Optional[List[str]] = None

class ActorLocalizerPreviewRequest(BaseModel):
    target: TargetScope
    config: ActorLocalizerConfig

class ActorLocalizerApplyRequest(BaseModel):
    items: List[Dict]


class SuggestRolesRequest(BaseModel):
    item_id: str
    actor_names: List[str]

class UpdateRolesRequest(BaseModel):
    item_id: str
    people: List[Dict]

class MediaSearchQuery(BaseModel):
    query: str

class DownloadRequest(BaseModel):
    item_id: str
    content_types: List[str]

class BatchDownloadRequest(BaseModel):
    mode: Literal["byType", "byLibrary", "all"]
    content_types: List[str]
    media_type: Optional[Literal["Movie", "Series"]] = None
    library_ids: Optional[List[str]] = None
    blacklist: Optional[str] = None

class ActorGalleryMatchRequest(BaseModel):
    item_id: str
    item_name: str
    person_name: str
class ActorGalleryUploadRequest(BaseModel):
    person_id: str
    image_url: str
    new_name: Optional[str] = None
    source: Optional[Literal['douban', 'tmdb']] = 'tmdb'
    tmdb_person_id: Optional[int] = None

class PosterUploadRequest(BaseModel):
    item_id: str
    image_url: str
    source: Optional[Literal['douban', 'tmdb']] = 'tmdb'

class TmdbImageRequest(BaseModel):
    item_id: str
    image_type: Literal['poster', 'backdrop', 'logo']
class TmdbConfirmRequest(BaseModel):
    item_id: str
    tmdb_id: int
    image_type: Literal['poster', 'backdrop', 'logo']
class TmdbCandidate(BaseModel):
    id: int
    title: str
    release_date: Optional[str] = None
    poster_path: Optional[str] = None
    overview: Optional[str] = None
class TmdbImage(BaseModel):
    file_path: str
    vote_average: float
    iso_639_1: Optional[str] = None
class TmdbImageResponse(BaseModel):
    status: Literal['success', 'single_candidate_confirm', 'manual_selection', 'not_found', 'error']
    images: Optional[List[TmdbImage]] = None
    candidates: Optional[List[TmdbCandidate]] = None
    message: Optional[str] = None
class ActorTmdbImageFlowRequest(BaseModel):
    emby_person_id: str
    emby_person_name: str
    emby_media_item_id: str
    force_context_list: bool = False
    force_manual_search: bool = False
    confirmed_tmdb_person_id: Optional[int] = None
class TmdbPersonCandidate(BaseModel):
    id: int
    name: str
    profile_path: Optional[str] = None
    known_for_department: Optional[str] = None
    known_for_titles: List[str] = Field(default_factory=list)
class SingleActorConfirmContext(BaseModel):
    media: Dict[str, Any]
    person: Dict[str, Any]
class ActorTmdbImageFlowResponse(BaseModel):
    status: Literal['success', 'single_actor_confirm', 'context_manual_selection', 'manual_actor_selection', 'not_found', 'error']
    images: Optional[List[TmdbImage]] = None
    candidates: Optional[List[TmdbPersonCandidate]] = None
    context: Optional[SingleActorConfirmContext] = None
    message: Optional[str] = None

class UpdateDoubanIdRequest(BaseModel):
    douban_id: str

class CombinedImage(BaseModel):
    file_path: str
    source: Literal['douban', 'tmdb']
    vote_average: Optional[float] = 0.0
    iso_639_1: Optional[str] = None

class CombinedImageResponse(BaseModel):
    success: bool
    images: List[CombinedImage] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class CombinedAvatarRequest(BaseModel):
    emby_person_id: str
    emby_person_name: str
    emby_media_item_id: str
    confirmed_tmdb_person_id: Optional[int] = None
    confirmed_douban_actor: Optional[Dict[str, Any]] = None
    
    confirmed_douban_images: List[Dict[str, Any]] = Field(default_factory=list)

    skip_douban: bool = Field(default=False, description="是否跳过豆瓣源的匹配")
    skip_tmdb: bool = Field(default=False, description="是否跳过TMDB源的匹配")
    force_tmdb_context_list: bool = Field(default=False, description="是否强制TMDB返回上下文列表")
    force_tmdb_global_search: bool = Field(default=False, description="是否强制TMDB进行全局搜索")

class CombinedActorImage(BaseModel):
    file_path: str
    source: Literal['douban', 'tmdb']
    vote_average: Optional[float] = 0.0
    iso_639_1: Optional[str] = None
    actor_name: Optional[str] = None

class CombinedAvatarResponse(BaseModel):
    status: Literal[
        'success',
        'douban_manual_selection',
        'tmdb_single_actor_confirm',
        'tmdb_context_manual_selection',
        'tmdb_manual_actor_selection',
        'all_failed'
    ]
    images: List[CombinedActorImage] = Field(default_factory=list)
    intervention_details: Optional[Any] = None
    warnings: List[str] = Field(default_factory=list)

class LocalExtractRequest(BaseModel):
    """本地提取请求模型 (新版)"""
    source_path: str
    extensions: List[str] = Field(default_factory=list)
    filenames: List[str] = Field(default_factory=list)

class EmbyWebhookItem(BaseModel):
    Name: str
    Id: str
    Type: str



class PreciseScreenshotUpdateRequest(BaseModel):
    """精准截图更新请求模型"""
    series_tmdb_id: str
    series_name: str
    episodes: List[Dict[str, Any]] # 包含 season_number, episode_number 的字典列表
    config: "EpisodeRefresherConfig"

class EmbyWebhookPayload(BaseModel):
    Event: str
    User: Optional[Dict[str, Any]] = None
    Item: Optional[EmbyWebhookItem] = None

    class Config:
        extra = 'ignore'

