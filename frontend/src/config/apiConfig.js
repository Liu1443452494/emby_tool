// frontend/src/config/apiConfig.js (最终正确版)

// 这个文件用于统一管理所有与后端API相关的配置

const isDevelopment = import.meta.env.MODE === 'development';

// 后端 HTTP 服务的基础 URL
// 开发时，直接访问写死的后端地址。
// 生产（Docker）时，使用相对路径，让 Nginx 去处理代理。
const API_BASE_URL = isDevelopment ? 'http://127.0.0.1:8000' : '';

// 后端 WebSocket 服务的基础 URL
// 无论开发还是生产，这个变量都只包含协议、主机和端口，不包含路径。
const WS_BASE_URL = isDevelopment 
  ? 'ws://127.0.0.1:8000'
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;

// TMDB 图片服务相关配置
const TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/';

const TMDB_IMAGE_SIZES = {
  poster: 'w780',
  backdrop: 'w1280',
  avatar: 'h632',
  original: 'original'
};

export { 
  API_BASE_URL, 
  WS_BASE_URL,
  TMDB_IMAGE_BASE_URL,
  TMDB_IMAGE_SIZES
};