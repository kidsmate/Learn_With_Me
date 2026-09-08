/* ===== 本地数据存储模块 ===== */
const STORAGE_KEY = 'anran_learning_data';

// 默认数据结构
const DEFAULT_DATA = {
  nickname: '安冉',
  dailyGoal: 3,
  points: 0,
  streak: 0,
  lastCheckinDate: null,
  checkinDates: [],        // 打卡日期列表 ['2026-09-01', ...]
  learnedPoints: {},       // { pointId: learnedAt }
  records: [],             // { type: 'learn'|'reward'|'punish'|'redeem'|'checkin', name, value, time }
  wishes: [],              // { id, name, icon, cost, granted }
  textbooks: [],           // { id, name, subject, size, uploadTime, chapters }
};

function loadData() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_DATA };
    const data = JSON.parse(raw);
    // 合并默认值，确保新增字段存在
    return { ...DEFAULT_DATA, ...data };
  } catch (e) {
    console.error('加载数据失败', e);
    return { ...DEFAULT_DATA };
  }
}

function saveData(data) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch (e) {
    console.error('保存数据失败', e);
  }
}

function resetData() {
  localStorage.removeItem(STORAGE_KEY);
}

// 日期工具
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

function isTodayChecked(data) {
  return data.checkinDates.includes(todayStr());
}

function isYesterdayChecked(data) {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  const y = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  return data.checkinDates.includes(y);
}

// 添加记录
function addRecord(data, type, name, value) {
  data.records.unshift({
    type, name, value,
    time: Date.now(),
    date: todayStr()
  });
  // 保留最近 200 条
  if (data.records.length > 200) data.records = data.records.slice(0, 200);
}

// 检查是否完成每日目标
function isDailyGoalDone(data) {
  const today = todayStr();
  const todayLearned = Object.values(data.learnedPoints).filter(t => {
    const d = new Date(t);
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` === today;
  }).length;
  return todayLearned >= data.dailyGoal;
}

// 今日已学知识点数
function todayLearnedCount(data) {
  const today = todayStr();
  return Object.values(data.learnedPoints).filter(t => {
    const d = new Date(t);
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` === today;
  }).length;
}

// 本周打卡天数
function thisWeekCheckinCount(data) {
  const now = new Date();
  const day = now.getDay();
  const monday = new Date(now);
  monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
  monday.setHours(0,0,0,0);
  return data.checkinDates.filter(d => new Date(d) >= monday).length;
}

// 已掌握知识点总数
function masteredCount(data) {
  return Object.keys(data.learnedPoints).length;
}

// 总知识点数
function totalPointsCount() {
  let total = 0;
  SUBJECTS.forEach(s => s.chapters.forEach(c => total += c.points.length));
  return total;
}
