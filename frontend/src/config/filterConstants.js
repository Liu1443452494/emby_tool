// frontend/src/config/filterConstants.js (新文件)

// 类型映射
export const GENRE_MAP = {
  'action': '动作',
  'adventure': '冒险',
  'animation': '动画',
  'anime': '日式动画',
  'comedy': '喜剧',
  'crime': '犯罪',
  'disaster': '灾难',
  'documentary': '纪录片',
  'drama': '剧情',
  'eastern': '东方',
  'family': '家庭',
  'fan-film': '同人电影',
  'fantasy': '奇幻',
  'film-noir': '黑色电影',
  'game-show': '游戏节目',
  'history': '历史',
  'holiday': '假日',
  'horror': '恐怖',
  'indie': '独立',
  'music': '音乐',
  'musical': '歌舞',
  'mystery': '悬疑',
  'news': '新闻',
  'none': '无',
  'reality': '真人秀',
  'road': '公路',
  'romance': '爱情',
  'science-fiction': '科幻',
  'short': '短片',
  'sporting-event': '体育赛事',
  'sports': '运动',
  'stand-up': '脱口秀',
  'suspense': '悬念',
  'talk-show': '访谈',
  'thriller': '惊悚',
  'tv-movie': '电视电影',
  'war': '战争',
  'western': '西部'
};

// 国家/地区映射
export const COUNTRY_MAP = {
  'cn': '中国大陆',
  'hk': '中国香港',
  'tw': '中国台湾',
  'us': '美国',
  'jp': '日本',
  'gb': '英国',
  'kr': '韩国',
  'fr': '法国',
  'de': '德国',
  'in': '印度',
  'th': '泰国',
  'ca': '加拿大',
  'au': '澳大利亚',
  'ru': '俄罗斯'
};

// 语言映射
export const LANGUAGE_MAP = {
  'zh': '中文',
  'en': '英文',
  'ja': '日语',
  'ko': '韩语',
  'fr': '法语',
  'de': '德语',
  'es': '西班牙语',
  'ru': '俄语',
  'th': '泰语'
};

// 将映射转换为 el-select 需要的 { value, label } 格式
export const mapToOptions = (map) => {
  return Object.entries(map).map(([value, label]) => ({ value, label }));
};