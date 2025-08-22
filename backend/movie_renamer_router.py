# backend/movie_renamer_router.py (新文件)

# 这个文件目前为空，为未来可能的独立 API 预留。
# 当前功能通过 main.py 中的 trigger_scheduled_task 触发，
# 共享配置也通过 episode_renamer_router 保存，所以暂时不需要独立的 API。

from fastapi import APIRouter

router = APIRouter()

# 可以在这里添加未来特定于电影重命名的 API，例如独立配置的保存等。