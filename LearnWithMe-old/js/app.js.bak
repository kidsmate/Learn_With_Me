/* ===== 安冉的学习助手 - 主逻辑 ===== */
let state = loadData();
let currentSubject = null;
let currentKnowledge = null;
let calMonth = new Date().getMonth();
let calYear = new Date().getFullYear();
let selectedWishIcon = '🎁';
let currentPdfData = null;

// ============ IndexedDB 工具（保存 PDF 原始文件）============
const DB_NAME = 'anran_learning';
const DB_VERSION = 1;
const STORE_NAME = 'pdf_files';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function savePdfToDB(id, arrayBuffer, name) {
  return openDB().then(db => new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put({ id, data: arrayBuffer, name, savedAt: Date.now() });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  }));
}

function loadPdfFromDB(id) {
  return openDB().then(db => new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const req = tx.objectStore(STORE_NAME).get(id);
    req.onsuccess = () => resolve(req.result ? req.result.data : null);
    req.onerror = () => reject(req.error);
  }));
}

function deletePdfFromDB(id) {
  return openDB().then(db => new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  }));
}

// PDF.js 文档缓存
const _pdfDocCache = {};
async function getPdfDoc(textbookId, arrayBuffer) {
  if (_pdfDocCache[textbookId]) {
    console.log('[PDF] 使用缓存的文档:', textbookId);
    return _pdfDocCache[textbookId];
  }
  if (!arrayBuffer) {
    console.log('[PDF] 从 IndexedDB 加载:', textbookId);
    arrayBuffer = await loadPdfFromDB(textbookId);
  }
  if (!arrayBuffer) {
    console.error('[PDF] IndexedDB 中未找到 PDF:', textbookId);
    return null;
  }
  console.log('[PDF] PDF 数据大小:', arrayBuffer.byteLength, 'bytes');
  const doc = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  console.log('[PDF] 文档加载成功，共', doc.numPages, '页');
  _pdfDocCache[textbookId] = doc;
  return doc;
}

// ============ 初始化 ============
function init() {
  renderAll();
  setupEventListeners();
  // 设置 PDF.js worker
  if (window.pdfjsLib) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  }
}

function renderAll() {
  updateTopBar();
  renderDashboard();
  renderSubjects();
  renderRewards();
  renderWishlist();
  renderTextbooks();
  renderSettings();
}

// ============ 顶部栏 ============
function updateTopBar() {
  document.getElementById('pointsValue').textContent = state.points;
  document.getElementById('streakValue').textContent = state.streak;
}

// ============ 仪表盘 ============
function renderDashboard() {
  // 日期
  const d = new Date();
  const weekdays = ['日','一','二','三','四','五','六'];
  document.getElementById('todayDate').textContent =
    `${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日 星期${weekdays[d.getDay()]}`;

  // 问候
  const hour = d.getHours();
  let greet = '早上好';
  if (hour >= 11 && hour < 13) greet = '中午好';
  else if (hour >= 13 && hour < 18) greet = '下午好';
  else if (hour >= 18) greet = '晚上好';
  document.getElementById('greetingTitle').textContent = `${greet}，${state.nickname}！`;
  document.getElementById('dailyQuote').textContent =
    DAILY_QUOTES[Math.floor(Math.random() * DAILY_QUOTES.length)];

  // 打卡按钮
  const btn = document.getElementById('btnDailyCheckin');
  if (isTodayChecked(state)) {
    btn.textContent = '✓ 已打卡';
    btn.classList.add('done');
    btn.disabled = true;
  } else {
    btn.textContent = '每日打卡';
    btn.classList.remove('done');
    btn.disabled = false;
  }

  // 今日任务 - 推荐未学的知识点
  renderTodayTasks();

  // 统计
  document.getElementById('statLearned').textContent = masteredCount(state);
  document.getElementById('statMastered').textContent = masteredCount(state);
  document.getElementById('statThisWeek').textContent = thisWeekCheckinCount(state);
  document.getElementById('statDays').textContent = state.checkinDates.length;

  // 日历
  renderCalendar();
}

function renderTodayTasks() {
  const grid = document.getElementById('todayTasks');
  // 找未学的知识点，每个学科取1个，凑够 dailyGoal 个
  const tasks = [];
  for (const subj of SUBJECTS) {
    for (const chap of subj.chapters) {
      for (const p of chap.points) {
        if (!state.learnedPoints[p.id] && tasks.length < state.dailyGoal) {
          tasks.push({ subject: subj, point: p });
        }
      }
    }
    if (tasks.length >= state.dailyGoal) break;
  }

  if (tasks.length === 0) {
    grid.innerHTML = '<div class="empty-state"><div class="empty-icon">🎉</div>太棒了！所有知识点都学完啦</div>';
    return;
  }

  const today = todayStr();
  const todayCount = todayLearnedCount(state);

  grid.innerHTML = tasks.map(t => {
    const learned = !!state.learnedPoints[t.point.id];
    return `
      <div class="task-card ${learned ? 'done' : ''}" onclick="openKnowledge('${t.subject.id}','${t.point.id}')">
        <div class="task-icon" style="background:${hexToRgba(t.subject.color,0.12)}">${t.subject.icon}</div>
        <div class="task-info">
          <div class="task-name">${t.point.title}</div>
          <div class="task-sub">${t.subject.name} · ${t.subject.chapters.find(c=>c.points.some(p=>p.id===t.point.id)).title}</div>
        </div>
        <div class="task-check">${learned ? '✓' : ''}</div>
      </div>
    `;
  }).join('');

  // 今日进度提示
  if (todayCount >= state.dailyGoal) {
    grid.insertAdjacentHTML('beforebegin',
      `<div style="background:linear-gradient(135deg,#00B894,#55EFC4);color:white;padding:12px 16px;border-radius:12px;margin-bottom:12px;font-weight:600;">
        🎉 今日目标已完成（${todayCount}/${state.dailyGoal}），继续保持！
      </div>`);
  }
}

function renderCalendar() {
  const monthNames = ['一月','二月','三月','四月','五月','六月','七月','八月','九月','十月','十一月','十二月'];
  document.getElementById('calTitle').textContent = `${calYear}年 ${monthNames[calMonth]}`;

  const firstDay = new Date(calYear, calMonth, 1).getDay();
  const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
  const today = todayStr();

  let html = '';
  for (let i = 0; i < firstDay; i++) html += '<div class="cal-day empty"></div>';
  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = `${calYear}-${String(calMonth+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
    const checked = state.checkinDates.includes(dateStr);
    const isToday = dateStr === today;
    const classes = ['cal-day'];
    if (checked) classes.push('checked');
    if (isToday) classes.push('today');
    html += `<div class="${classes.join(' ')}">${day}</div>`;
  }
  document.getElementById('calendarGrid').innerHTML = html;
}

// ============ 每日打卡 ============
function dailyCheckin() {
  if (isTodayChecked(state)) {
    showToast('今天已经打卡过啦～');
    return;
  }
  const today = todayStr();
  state.checkinDates.push(today);

  // 连续打卡
  if (isYesterdayChecked(state) || state.streak === 0) {
    state.streak += 1;
  } else {
    state.streak = 1;
  }

  // 打卡奖励
  state.points += 10;
  addRecord(state, 'reward', '每日打卡', 10);

  // 连续7天额外奖励
  if (state.streak > 0 && state.streak % 7 === 0) {
    state.points += 30;
    addRecord(state, 'reward', `连续打卡${state.streak}天奖励`, 30);
    showToast(`🔥 连续打卡${state.streak}天！额外奖励30积分`);
  } else {
    showToast('🎉 打卡成功！+10积分');
  }

  saveData(state);
  renderAll();
}

// ============ 学科列表 ============
function renderSubjects() {
  const grid = document.getElementById('subjectsGrid');
  grid.innerHTML = SUBJECTS.map(s => {
    let total = 0, learned = 0;
    s.chapters.forEach(c => c.points.forEach(p => {
      total++;
      if (state.learnedPoints[p.id]) learned++;
    }));
    const pct = total ? Math.round(learned / total * 100) : 0;
    return `
      <div class="subject-card" style="border-top-color:${s.color}" onclick="openSubject('${s.id}')">
        <div class="subject-icon">${s.icon}</div>
        <div class="subject-name">${s.name}</div>
        <div class="subject-desc">${s.desc}</div>
        <div class="subject-progress-mini"><div class="fill" style="width:${pct}%;background:${s.color}"></div></div>
        <div class="subject-progress-text">${learned} / ${total} 知识点</div>
      </div>
    `;
  }).join('');
}

// ============ 学科详情 ============
function openSubject(subjectId) {
  currentSubject = SUBJECTS.find(s => s.id === subjectId);
  if (!currentSubject) return;
  document.getElementById('subjectDetailTitle').textContent = `${currentSubject.icon} ${currentSubject.name}`;

  let total = 0, learned = 0;
  currentSubject.chapters.forEach(c => c.points.forEach(p => {
    total++;
    if (state.learnedPoints[p.id]) learned++;
  }));
  const pct = total ? Math.round(learned / total * 100) : 0;
  document.getElementById('subjectProgressFill').style.width = pct + '%';
  document.getElementById('subjectProgressText').textContent = `${learned} / ${total}（${pct}%）`;

  const list = document.getElementById('knowledgeList');
  list.innerHTML = currentSubject.chapters.map(c => `
    <div class="chapter-block">
      <div class="section-title" style="color:${currentSubject.color}">📚 ${c.title}</div>
      ${c.points.map(p => {
        const isLearned = !!state.learnedPoints[p.id];
        return `
          <div class="kp-item ${isLearned ? 'learned' : ''}" onclick="openKnowledge('${currentSubject.id}','${p.id}')">
            <div class="kp-status">${isLearned ? '✓' : ''}</div>
            <div class="kp-info">
              <div class="kp-title">${p.title}</div>
              <div class="kp-chapter">${c.title}</div>
            </div>
            <div class="kp-action">${isLearned ? '已掌握' : '去学习'}</div>
          </div>
        `;
      }).join('')}
    </div>
  `).join('');

  navigate('subject-detail');
}

// ============ 知识点详情（学习页）============
function openKnowledge(subjectId, pointId) {
  const subj = SUBJECTS.find(s => s.id === subjectId);
  const point = subj.chapters.flatMap(c => c.points).find(p => p.id === pointId);
  if (!point) return;
  currentKnowledge = { subject: subj, point };
  openLearnPage(subj, point);
}

function openLearnPage(subj, point) {
  currentKnowledge = { subject: subj, point };
  document.getElementById('learnTitle').textContent = point.title;
  document.getElementById('learnSubjectTag').innerHTML =
    `<span class="badge" style="background:${hexToRgba(subj.color,0.12)};color:${subj.color};padding:6px 14px;border-radius:8px;font-size:14px;font-weight:600;">${subj.icon} ${subj.name}</span>`;

  const content = LEARNING_CONTENT[point.id] || {};

  // 知识总结
  document.getElementById('learnSummary').innerHTML = `
    <div class="learn-section-title">📝 知识总结</div>
    <p class="learn-text">${content.summary || point.content || '暂无总结内容'}</p>
  `;

  // 核心要点
  const kps = content.keyPoints || [];
  document.getElementById('learnKeyPoints').innerHTML = `
    <div class="learn-section-title">🔑 核心要点</div>
    ${kps.length ? kps.map((k, i) => `
      <div class="keypoint-item">
        <div class="kp-num">${i+1}</div>
        <div class="kp-text">${k}</div>
      </div>
    `).join('') : '<p class="learn-text">暂无核心要点</p>'}
  `;

  // 教材内容（从上传的 PDF 关联）
  renderLearnTextbook(subj, point);

  // 教学视频
  renderLearnVideo(content.videoKeywords || point.title);

  // 习题练习
  const exs = content.exercises || [];
  document.getElementById('learnExercise').innerHTML = `
    <div class="learn-section-title">✏️ 习题练习</div>
    ${exs.length ? exs.map((e, i) => `
      <div class="exercise-item" id="ex-${i}">
        <div class="ex-q"><span class="ex-tag">第${i+1}题</span>${e.q}</div>
        <div class="ex-answer" id="ex-ans-${i}" style="display:none;">
          <div class="ex-ans-label">参考答案</div>
          <div class="ex-ans-text">${e.a}</div>
          <div class="ex-exp-label">解析</div>
          <div class="ex-exp-text">${e.e}</div>
        </div>
        <button class="btn-secondary ex-toggle" onclick="toggleAnswer(${i})" id="ex-btn-${i}">查看答案与解析</button>
      </div>
    `).join('') : '<p class="learn-text">暂无习题</p>'}
  `;

  // 标记已学按钮状态
  const isLearned = !!state.learnedPoints[point.id];
  const btn = document.getElementById('learnMarkBtn');
  if (isLearned) {
    btn.textContent = '取消标记 (-5🪙)';
    btn.style.background = 'var(--danger)';
  } else {
    btn.textContent = '标记已学 (+5🪙)';
    btn.style.background = 'var(--accent)';
  }

  // 默认显示第一个 tab
  switchLearnSection('summary');
  document.querySelectorAll('.learn-tab').forEach(t => t.classList.toggle('active', t.dataset.section === 'summary'));

  navigate('learn');
}

// 记录当前选中的教材章节索引 {textbookIdx: sectionIdx}
const currentTbSelection = {};
// 缓存当前渲染的教材列表（供 selectTbSection 访问 sections 数据）
let _renderedTextbooks = [];

function renderLearnTextbook(subj, point) {
  const textbooks = state.textbooks.filter(t => t.subject === subj.name || t.subject === '');
  _renderedTextbooks = textbooks;
  const container = document.getElementById('learnTextbook');
  
  if (textbooks.length === 0) {
    container.innerHTML = `
      <div class="learn-section-title">📖 教材内容</div>
      <div class="empty-state">
        <div class="empty-icon">📚</div>
        <p>尚未上传 ${subj.name} 教材</p>
        <p style="font-size:13px;margin-top:8px;">前往"教材"页面上传人教版${subj.name}教材 PDF，系统将自动按单元整理课文</p>
      </div>
    `;
    return;
  }

  let html = `<div class="learn-section-title">📖 教材内容（${subj.name}）</div>`;
  
  textbooks.forEach((t, ti) => {
    const units = t.units && t.units.length ? t.units : null;
    const sections = t.sections || [];
    const chapters = t.chapters || [];
    window._renderedTextbook = window._renderedTextbook || {};
    window._renderedTextbook[ti] = t;
    
    html += `<div class="textbook-ref">`;
    html += `<div class="textbook-ref-name">📄 ${t.name}</div>`;
    const totalLessons = units ? units.reduce((s, u) => s + u.lessons.length, 0) : sections.length;
    html += `<div class="textbook-ref-meta">上传于 ${formatTime(t.uploadTime)} · ${units ? units.length + ' 个单元' : sections.length + ' 个章节'} · ${totalLessons} 篇课文</div>`;

    if (!units && sections.length === 0) {
      html += `
        <div class="textbook-old-notice">
          ⚠️ 该教材为旧版数据，未保存正文内容。请删除后重新上传以查看完整教材正文。
        </div>
        ${chapters.length ? '<div class="chapters-mini">' + chapters.slice(0, 15).map((c, i) => `<span class="chapter-chip">${i+1}. ${c}</span>`).join('') + '</div>' : ''}
      `;
    } else {
      // 优先使用 units 结构；若没有 units 则把 sections 包装成一个单元
      const bookUnits = units || [{ title: '教材内容', lessons: sections.map(s => ({ title: s.title, content: s.content })) }];
      html += renderBookReader(bookUnits, ti, point);
    }
    html += `</div>`;
  });
  
  container.innerHTML = html;
}

// 渲染书本式阅读器：左侧目录 + 右侧正文（左右分栏）
function renderBookReader(units, ti, point) {
  let html = '';
  const readerId = `reader-${ti}`;

  // 找到匹配的课文索引
  let matchedU = -1, matchedL = -1;
  units.forEach((u, ui) => {
    u.lessons.forEach((l, li) => {
      if (matchedU < 0 && point && (l.title.includes(point.title) || point.title.includes(l.title.substring(0, 2)) || findRelevantSection({sections:[{title:l.title,content:l.content}]}, point) === 0)) {
        matchedU = ui; matchedL = li;
      }
    });
  });
  if (matchedU < 0) { matchedU = 0; matchedL = 0; }

  // 构建所有课文的扁平列表（仅 type=lesson 的文章，group 不参与导航）
  const allLessons = [];
  units.forEach((u, ui) => {
    u.lessons.forEach((l, li) => {
      if (l.type !== 'group') {
        allLessons.push({ unitTitle: u.title, ui, li, ...l });
      }
    });
  });
  let flatIdx = matchedU >= 0 ? allLessons.findIndex(l => l.ui === matchedU && l.li === matchedL) : 0;
  if (flatIdx < 0) flatIdx = 0;

  // 存储当前选中状态
  window._tbSelection = window._tbSelection || {};
  window._tbSelection[ti] = { flatIdx };

  html += `<div class="tb-reader" id="${readerId}">`;

  // ===== 左侧目录 =====
  html += `<div class="tb-toc">`;
  html += `<div class="tb-toc-title">📑 目录</div>`;
  html += `<div class="tb-toc-list" id="tb-toc-list-${ti}">`;
  // 如果没有任何可点击课文，显示提示
  if (allLessons.length === 0) {
    html += `<div class="tb-toc-empty">未识别到课文，请尝试重新上传教材</div>`;
  }
  units.forEach((u, ui) => {
    html += `<div class="tb-toc-unit-label">${escapeHtml(u.title)}</div>`;
    u.lessons.forEach((l, li) => {
      if (l.type === 'group') {
        // 二级栏目：缩进一级，不可点击
        html += `<div class="tb-toc-group">${escapeHtml(l.title)}</div>`;
      } else {
        // 三级文章：缩进两级，可点击
        const fIdx = allLessons.findIndex(x => x.ui === ui && x.li === li);
        const active = (ui === matchedU && li === matchedL);
        const pageTag = l.startPage ? `<span class="tb-toc-page">${l.startPage}</span>` : '';
        html += `
          <div class="tb-toc-item tb-toc-lesson ${active ? 'active' : ''}" 
               id="tb-toc-item-${ti}-${fIdx}"
               onclick="selectBookLesson('${ti}', ${fIdx})">
            <span class="tb-toc-text">${escapeHtml(l.title)}</span>${pageTag}
          </div>
        `;
      }
    });
  });
  html += `</div></div>`;

  // ===== 右侧正文 =====
  html += `<div class="tb-content" id="tb-content-${ti}">`;
  if (allLessons.length > 0) {
    const cur = allLessons[flatIdx];
    html += `<div class="tb-content-header">`;
    html += `<div class="tb-content-unit" id="tb-content-unit-${ti}">${escapeHtml(cur.unitTitle)}</div>`;
    html += `<h2 class="tb-content-title" id="tb-content-title-${ti}">${escapeHtml(cur.title)}</h2>`;
    html += `<div class="tb-content-nav">`;
    html += `<button class="btn-secondary btn-sm" onclick="navBookLesson('${ti}', -1)" ${flatIdx === 0 ? 'disabled' : ''}>← 上一篇</button>`;
    html += `<span class="tb-content-page">${flatIdx+1} / ${allLessons.length}</span>`;
    html += `<button class="btn-secondary btn-sm" onclick="navBookLesson('${ti}', 1)" ${flatIdx === allLessons.length-1 ? 'disabled' : ''}>下一篇 →</button>`;
    html += `</div></div>`;
    html += `<div class="tb-content-body" id="tb-content-body-${ti}">`;
    html += formatTextbookContent(cur.content);
    html += `</div>`;
  } else {
    html += `<div class="tb-content-body" id="tb-content-body-${ti}" style="display:flex;align-items:center;justify-content:center;">
      <div class="empty-state"><div class="empty-icon">📄</div><p>未识别到课文内容</p><p style="font-size:13px;color:var(--text-light);">请删除后重新上传教材 PDF</p></div>
    </div>`;
  }
  html += `</div>`;

  html += `</div>`;

  // 存储课文数据供切换使用
  window._tbLessons = window._tbLessons || {};
  window._tbLessons[ti] = allLessons;
  window._tbSelection = window._tbSelection || {};
  window._tbSelection[ti] = { flatIdx };

  // 存储教材 ID 和是否有 PDF
  const textbook = window._renderedTextbook && window._renderedTextbook[ti];
  window._tbTextbookId = window._tbTextbookId || {};
  window._tbHasPdf = window._tbHasPdf || {};
  window._tbTextbookId[ti] = textbook ? textbook.id : null;
  window._tbHasPdf[ti] = textbook ? !!textbook.hasPdf : false;
  console.log('[教材阅读器] ti=', ti, 'textbook=', textbook ? { id: textbook.id, hasPdf: textbook.hasPdf, units: textbook.units && textbook.units.length } : null);

  // 如果有 PDF，初始也渲染 PDF 页面
  if (textbook && textbook.hasPdf && allLessons.length > 0) {
    const l = allLessons[flatIdx];
    console.log('[教材阅读器] 初始渲染 PDF，课文=', l.title, 'startPage=', l.startPage, 'endPage=', l.endPage);
    if (l.startPage) {
      const sp = l.startPage;
      const ep = l.endPage || l.startPage;
      setTimeout(() => {
        const bodyEl = document.getElementById(`tb-content-body-${ti}`);
        if (bodyEl) {
          bodyEl.innerHTML = `<div class="pdf-loading">📄 正在加载 PDF 第 ${sp} 页${ep > sp ? `（本文章 第 ${sp}-${ep} 页）` : ''}...</div>`;
          renderPdfPage(textbook.id, sp, bodyEl, l.title, sp, ep);
        }
      }, 100);
    }
  } else {
    console.log('[教材阅读器] 无 PDF，显示文本内容。hasPdf=', textbook && textbook.hasPdf);
  }

  return html;
}

// 选中课文（更新右侧正文，优先渲染 PDF 页面）
function selectBookLesson(ti, fIdx) {
  const lessons = window._tbLessons && window._tbLessons[ti];
  if (!lessons || !lessons[fIdx]) return;
  const l = lessons[fIdx];
  window._tbSelection[ti] = { flatIdx: fIdx };

  // 更新目录高亮
  document.querySelectorAll(`#tb-toc-list-${ti} .tb-toc-item`).forEach((el, idx) => {
    el.classList.toggle('active', idx === fIdx);
  });

  // 更新单元、标题
  const unitEl = document.getElementById(`tb-content-unit-${ti}`);
  if (unitEl) unitEl.textContent = l.unitTitle;
  const titleEl = document.getElementById(`tb-content-title-${ti}`);
  if (titleEl) titleEl.textContent = l.title;

  // 更新导航按钮
  const navEl = document.querySelector(`#tb-content-${ti} .tb-content-nav`);
  if (navEl) {
    navEl.innerHTML = `
      <button class="btn-secondary btn-sm" onclick="navBookLesson('${ti}', -1)" ${fIdx === 0 ? 'disabled' : ''}>← 上一篇</button>
      <span class="tb-content-page">${fIdx+1} / ${lessons.length}</span>
      <button class="btn-secondary btn-sm" onclick="navBookLesson('${ti}', 1)" ${fIdx === lessons.length-1 ? 'disabled' : ''}>下一篇 →</button>
    `;
  }

  // 渲染 PDF 页面（优先）或文本内容
  const bodyEl = document.getElementById(`tb-content-body-${ti}`);
  const textbookId = window._tbTextbookId && window._tbTextbookId[ti];
  const hasPdf = window._tbHasPdf && window._tbHasPdf[ti];

  if (hasPdf && textbookId && l.startPage) {
    const sp = l.startPage;
    const ep = l.endPage || l.startPage;
    bodyEl.innerHTML = `<div class="pdf-loading">📄 正在加载 PDF 第 ${sp} 页${ep > sp ? `（本文章 第 ${sp}-${ep} 页）` : ''}...</div>`;
    renderPdfPage(textbookId, sp, bodyEl, l.title, sp, ep);
  } else {
    bodyEl.innerHTML = formatTextbookContent(l.content);
  }

  // 滚动正文到顶部
  const contentEl = document.getElementById(`tb-content-${ti}`);
  if (contentEl) contentEl.scrollTop = 0;
}

// 用 PDF.js 渲染指定页码到容器
async function renderPdfPage(textbookId, pageNum, container, lessonTitle, startPage, endPage) {
  try {
    const doc = await getPdfDoc(textbookId);
    if (!doc) {
      container.innerHTML = `<div class="empty-state"><div class="empty-icon">📄</div><p>PDF 文件未找到，请重新上传教材</p></div>`;
      return;
    }
    if (pageNum > doc.numPages) pageNum = doc.numPages;
    if (pageNum < 1) pageNum = 1;
    const page = await doc.getPage(pageNum);
    const viewport = page.getViewport({ scale: 1.5 });

    // 清空容器
    container.innerHTML = '';

    // 文章页码范围（仅用于显示，不限制翻页）
    const sp = startPage || pageNum;
    const ep = endPage || pageNum;
    const rangeText = (ep > sp) ? `（本文章 第 ${sp}-${ep} 页）` : '';

    // 创建工具栏
    const info = document.createElement('div');
    info.className = 'pdf-page-info';

    const badge = document.createElement('span');
    badge.className = 'pdf-page-badge';
    badge.textContent = `第 ${pageNum} 页 / 共 ${doc.numPages} 页 ${rangeText}`;
    info.appendChild(badge);

    // 上一页按钮（在文章页码范围内翻页）
    const prevBtn = document.createElement('button');
    prevBtn.className = 'btn-secondary btn-sm';
    prevBtn.textContent = '上一页';
    prevBtn.disabled = pageNum <= sp;
    prevBtn.addEventListener('click', () => {
      renderPdfPage(textbookId, pageNum - 1, container, lessonTitle, sp, ep);
    });
    info.appendChild(prevBtn);

    // 下一页按钮（在文章页码范围内翻页）
    const nextBtn = document.createElement('button');
    nextBtn.className = 'btn-secondary btn-sm';
    nextBtn.textContent = '下一页';
    nextBtn.disabled = pageNum >= ep;
    nextBtn.addEventListener('click', () => {
      renderPdfPage(textbookId, pageNum + 1, container, lessonTitle, sp, ep);
    });
    info.appendChild(nextBtn);

    container.appendChild(info);

    // 渲染 canvas
    const canvas = document.createElement('canvas');
    canvas.className = 'pdf-canvas';
    const ctx = canvas.getContext('2d');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({ canvasContext: ctx, viewport }).promise;
    container.appendChild(canvas);
  } catch (err) {
    console.error('PDF 渲染失败:', err);
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><p>PDF 渲染失败：${err.message || '未知错误'}</p></div>`;
  }
}

// 上一篇/下一篇导航
function navBookLesson(ti, dir) {
  const lessons = window._tbLessons && window._tbLessons[ti];
  if (!lessons) return;
  const cur = (window._tbSelection && window._tbSelection[ti] && window._tbSelection[ti].flatIdx) || 0;
  const next = cur + dir;
  if (next >= 0 && next < lessons.length) {
    selectBookLesson(ti, next);
  }
}

// 根据知识点匹配教材中的相关章节（关键词重叠度）
function findRelevantSection(textbook, point) {
  if (!textbook.sections || textbook.sections.length === 0) return -1;
  // 停用词（常见无意义单字）
  const stopwords = new Set(['的','了','是','在','和','与','或','等','中','上','下','不','也','都','就','及','之','其','此','个','一','二','三','为','有','我','你','他','她','它','这','那','被','把','让','使','从','到','向','对','于']);
  // 提取知识点标题中的有效关键词（单字也保留，但过滤停用词）
  const pointText = point.title + ' ' + (point.content || '');
  const tokens = pointText.match(/[\u4e00-\u9fa5A-Za-z0-9]+/g) || [];
  const kwSet = new Set();
  tokens.forEach(t => {
    if (t.length >= 2) kwSet.add(t);
    else if (t.length === 1 && !stopwords.has(t)) kwSet.add(t);
  });
  let bestIdx = -1;
  let bestScore = 0;
  textbook.sections.forEach((sec, i) => {
    const titleText = sec.title;
    const bodyText = sec.content.substring(0, 500);
    let score = 0;
    kwSet.forEach(k => {
      if (titleText.includes(k)) score += (k.length >= 2 ? 3 : 1);  // 标题匹配
      else if (bodyText.includes(k)) score += (k.length >= 2 ? 1 : 0); // 正文匹配（单字不计）
    });
    if (score > bestScore) { bestScore = score; bestIdx = i; }
  });
  return bestScore >= 1 ? bestIdx : -1;
}

// 格式化教材正文（简单换行和段落处理）
function formatTextbookContent(text) {
  if (!text) return '<p style="color:var(--text-light);">暂无内容</p>';
  // 按换行符分段，过滤空行
  const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
  if (lines.length === 0) return '<p style="color:var(--text-light);">暂无内容</p>';
  return lines.map(l => `<p class="tb-paragraph">${escapeHtml(l)}</p>`).join('');
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function renderLearnVideo(keywords) {
  const encoded = encodeURIComponent(keywords);
  const bilibiliUrl = `https://search.bilibili.com/all?keyword=${encoded}`;
  document.getElementById('learnVideo').innerHTML = `
    <div class="learn-section-title">🎬 教学视频</div>
    <div class="video-card">
      <div class="video-search">
        <div class="video-search-icon">🔍</div>
        <div class="video-search-text">
          <div style="font-weight:600;margin-bottom:4px;">在 B 站搜索教学视频</div>
          <div style="font-size:13px;color:var(--text-light);">关键词：${keywords}</div>
        </div>
        <a href="${bilibiliUrl}" target="_blank" class="btn-primary" style="text-decoration:none;">去搜索</a>
      </div>
    </div>
    <div class="video-tips">
      <p>💡 建议在 B 站搜索以下关键词组合：</p>
      <div class="keyword-tags">
        <span class="kw-tag">${keywords}</span>
        <span class="kw-tag">${keywords} 人教版</span>
        <span class="kw-tag">${keywords} 初中</span>
        <span class="kw-tag">${keywords} 讲解</span>
      </div>
      <p style="margin-top:12px;font-size:13px;color:var(--text-light);">点击上方"去搜索"按钮，将跳转至 B 站搜索相关教学视频。选择播放量高、评价好的视频观看学习效果更佳。</p>
    </div>
  `;
}

function switchLearnSection(section) {
  document.querySelectorAll('.learn-section').forEach(s => s.classList.remove('active'));
  document.getElementById('learn-section-' + section).classList.add('active');
  document.querySelectorAll('.learn-tab').forEach(t => t.classList.toggle('active', t.dataset.section === section));
}

function toggleAnswer(index) {
  const ans = document.getElementById('ex-ans-' + index);
  const btn = document.getElementById('ex-btn-' + index);
  if (ans.style.display === 'none') {
    ans.style.display = 'block';
    btn.textContent = '收起答案';
  } else {
    ans.style.display = 'none';
    btn.textContent = '查看答案与解析';
  }
}

function markLearnedFromPage() {
  if (!currentKnowledge) return;
  markLearned();
  // 重新渲染按钮
  const isLearned = !!state.learnedPoints[currentKnowledge.point.id];
  const btn = document.getElementById('learnMarkBtn');
  if (isLearned) {
    btn.textContent = '取消标记 (-5🪙)';
    btn.style.background = 'var(--danger)';
  } else {
    btn.textContent = '标记已学 (+5🪙)';
    btn.style.background = 'var(--accent)';
  }
}

function markLearned() {
  if (!currentKnowledge) return;
  const { point } = currentKnowledge;
  if (state.learnedPoints[point.id]) {
    delete state.learnedPoints[point.id];
    state.points = Math.max(0, state.points - 5);
    addRecord(state, 'punish', `取消学习：${point.title}`, -5);
    showToast('已取消标记，-5积分');
  } else {
    state.learnedPoints[point.id] = Date.now();
    state.points += 5;
    addRecord(state, 'learn', `学习：${point.title}`, 5);
    showToast('🎉 学习完成！+5积分');
    if (isDailyGoalDone(state)) {
      state.points += 10;
      addRecord(state, 'reward', '完成每日目标', 10);
      setTimeout(() => showToast('🎯 完成每日目标！额外+10积分'), 600);
    }
  }
  saveData(state);
  updateTopBar();
  if (currentSubject) openSubject(currentSubject.id);
}

function closeModal() {
  document.getElementById('knowledgeModal').classList.remove('show');
  document.getElementById('btnMarkLearned').style.display = '';
  // 恢复弹窗默认样式
  const modalContent = document.querySelector('#knowledgeModal .modal-content');
  if (modalContent) modalContent.classList.remove('modal-wide');
  const modalFooter = document.querySelector('#knowledgeModal .modal-footer');
  if (modalFooter) modalFooter.style.display = '';
  currentKnowledge = null;
}

// ============ 激励中心 ============
function renderRewards() {
  // 正向规则
  document.getElementById('positiveRules').innerHTML = POSITIVE_RULES.map(r => `
    <div class="rule-item">
      <div class="rule-icon">${r.icon}</div>
      <div class="rule-info">
        <div class="rule-name">${r.name}</div>
        <div class="rule-desc">${r.desc}</div>
      </div>
      <div class="rule-value positive">${r.value}🪙</div>
    </div>
  `).join('');

  // 惩罚规则
  document.getElementById('negativeRules').innerHTML = NEGATIVE_RULES.map(r => `
    <div class="rule-item">
      <div class="rule-icon">${r.icon}</div>
      <div class="rule-info">
        <div class="rule-name">${r.name}</div>
        <div class="rule-desc">${r.desc}</div>
      </div>
      <div class="rule-value negative">${r.value}🪙</div>
    </div>
  `).join('');

  // 奖励记录
  const rewards = state.records.filter(r => r.type === 'reward' || r.type === 'learn');
  document.getElementById('rewardRecords').innerHTML = rewards.length ? rewards.slice(0, 30).map(r => `
    <div class="record-item">
      <div class="record-left">
        <div class="record-icon">${r.type === 'learn' ? '📖' : '🎁'}</div>
        <div>
          <div class="record-name">${r.name}</div>
          <div class="record-time">${formatTime(r.time)}</div>
        </div>
      </div>
      <div class="record-value positive">+${r.value}🪙</div>
    </div>
  `).join('') : '<div class="empty-state">暂无奖励记录</div>';

  // 惩罚记录
  const punishes = state.records.filter(r => r.type === 'punish' || r.type === 'redeem');
  document.getElementById('punishRecords').innerHTML = punishes.length ? punishes.slice(0, 30).map(r => `
    <div class="record-item">
      <div class="record-left">
        <div class="record-icon">${r.type === 'redeem' ? '🌟' : '⚠️'}</div>
        <div>
          <div class="record-name">${r.name}</div>
          <div class="record-time">${formatTime(r.time)}</div>
        </div>
      </div>
      <div class="record-value negative">${r.value}🪙</div>
    </div>
  `).join('') : '<div class="empty-state">暂无惩罚记录</div>';
}

// ============ 心愿清单 ============
function renderWishlist() {
  document.getElementById('wishPoints').textContent = state.points;
  const grid = document.getElementById('wishlistGrid');
  if (state.wishes.length === 0) {
    grid.innerHTML = '<div class="empty-state"><div class="empty-icon">🌟</div>还没有心愿，点击右上角添加吧</div>';
    return;
  }
  grid.innerHTML = state.wishes.map(w => `
    <div class="wish-card ${w.granted ? 'granted' : ''}">
      <div class="wish-icon">${w.icon}</div>
      <div class="wish-name">${w.name}</div>
      <div class="wish-cost">${w.cost} 🪙</div>
      ${w.granted
        ? '<div class="wish-status">✓ 已实现</div>'
        : `<div class="wish-actions">
             <button class="wish-btn redeem" ${state.points < w.cost ? 'disabled' : ''} onclick="redeemWish('${w.id}')">兑换</button>
             <button class="wish-btn delete" onclick="deleteWish('${w.id}')">删除</button>
           </div>`
      }
    </div>
  `).join('');
}

function openWishModal() {
  selectedWishIcon = '🎁';
  document.getElementById('wishName').value = '';
  document.getElementById('wishCost').value = '';
  document.querySelectorAll('#emojiPicker span').forEach(s => s.classList.remove('selected'));
  document.getElementById('wishModal').classList.add('show');
}

function closeWishModal() {
  document.getElementById('wishModal').classList.remove('show');
}

function saveWish() {
  const name = document.getElementById('wishName').value.trim();
  const cost = parseInt(document.getElementById('wishCost').value);
  if (!name) { showToast('请输入心愿名称'); return; }
  if (!cost || cost <= 0) { showToast('请输入有效的积分'); return; }
  state.wishes.push({
    id: 'w' + Date.now(),
    name, cost, icon: selectedWishIcon, granted: false
  });
  saveData(state);
  renderWishlist();
  closeWishModal();
  showToast('心愿已添加 🎉');
}

function redeemWish(id) {
  const w = state.wishes.find(x => x.id === id);
  if (!w || w.granted) return;
  if (state.points < w.cost) { showToast('积分不足，继续努力吧！'); return; }
  showConfirm(`确定用 ${w.cost} 积分兑换「${w.name}」吗？`, () => {
    state.points -= w.cost;
    w.granted = true;
    addRecord(state, 'redeem', `兑换心愿：${w.name}`, -w.cost);
    saveData(state);
    renderAll();
    showToast(`🌟 心愿「${w.name}」已实现！`);
  });
}

function deleteWish(id) {
  showConfirm('确定删除这个心愿吗？', () => {
    state.wishes = state.wishes.filter(w => w.id !== id);
    saveData(state);
    renderWishlist();
  });
}

// ============ 教材管理 ============
function renderTextbooks() {
  const list = document.getElementById('textbooksList');
  if (state.textbooks.length === 0) {
    list.innerHTML = '<div class="empty-state"><div class="empty-icon">📚</div>还没有上传教材，上传后可自动整理知识点</div>';
    return;
  }
  list.innerHTML = state.textbooks.map(t => {
    const unitCount = t.units && t.units.length ? t.units.length : 0;
    const lessonCount = t.units ? t.units.reduce((s, u) => s + u.lessons.length, 0) : (t.sections ? t.sections.length : 0);
    const hasContent = unitCount > 0 || (t.sections && t.sections.length > 0);
    return `
    <div class="textbook-item">
      <div class="textbook-icon">📄</div>
      <div class="textbook-info">
        <div class="textbook-name">${t.name}</div>
        <div class="textbook-meta">${t.subject || '未分类'} · ${unitCount ? unitCount + ' 个单元 / ' + lessonCount + ' 篇课文' : (t.chapters ? t.chapters.length + ' 个章节' : '0')}${hasContent ? '（含正文）' : ''} · ${formatSize(t.size)} · ${formatTime(t.uploadTime)}</div>
      </div>
      <button class="textbook-action" onclick="viewTextbook('${t.id}')">查看</button>
      <button class="textbook-action text-danger" onclick="deleteTextbook('${t.id}')">删除</button>
    </div>
  `;
  }).join('');
}

// 自定义确认弹窗（替代原生 confirm，移动端友好）
function showConfirm(msg, onOk) {
  const modal = document.getElementById('confirmModal');
  const msgEl = document.getElementById('confirmMsg');
  const okBtn = document.getElementById('confirmOk');
  const cancelBtn = document.getElementById('confirmCancel');
  if (msgEl) msgEl.textContent = msg;
  modal.classList.add('show');
  const cleanup = () => {
    modal.classList.remove('show');
    okBtn.onclick = null;
    cancelBtn.onclick = null;
  };
  okBtn.onclick = () => { cleanup(); onOk && onOk(); };
  cancelBtn.onclick = () => { cleanup(); };
}

function deleteTextbook(id) {
  showConfirm('确定删除该教材吗？删除后无法恢复。', () => {
    state.textbooks = state.textbooks.filter(t => t.id !== id);
    saveData(state);
    renderTextbooks();
    // 同时清理 IndexedDB 中的 PDF 数据
    deletePdfFromDB(id).catch(err => console.warn('清理 PDF 缓存失败:', err));
    // 清除 PDF.js 文档缓存
    if (_pdfDocCache[id]) {
      try { _pdfDocCache[id].destroy(); } catch(e) {}
      delete _pdfDocCache[id];
    }
    showToast('教材已删除');
  });
}

// 弹窗中当前查看的教材
let _modalTextbook = null;

function viewTextbook(id) {
  const t = state.textbooks.find(x => x.id === id);
  if (!t) return;
  _modalTextbook = t;
  const units = t.units && t.units.length ? t.units : null;
  const sections = t.sections || [];
  const totalLessons = units ? units.reduce((s, u) => s + u.lessons.length, 0) : sections.length;
  let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
    <h3 style="margin:0;">${t.name}</h3>
    <button class="btn-secondary btn-sm" onclick="openTocEditor('${t.id}')">✏️ 编辑目录</button>
  </div>
    <div style="color:var(--text-light);font-size:13px;margin-bottom:16px;">${t.subject || '未分类'} · ${units ? units.length + ' 个单元' : sections.length + ' 个章节'} · ${totalLessons} 篇课文 · ${formatSize(t.size)} · ${formatTime(t.uploadTime)}</div>`;
  
  if (units || sections.length > 0) {
    const bookUnits = units || [{ title: '教材内容', lessons: sections.map(s => ({ title: s.title, content: s.content, startPage: 1 })) }];
    window._renderedTextbook = window._renderedTextbook || {};
    window._renderedTextbook['m'] = t;
    html += renderBookReader(bookUnits, 'm', null);
  } else if (t.chapters && t.chapters.length) {
    html += '<div class="section-title">提取的章节（旧版数据，无正文）</div>';
    html += t.chapters.map((c, i) => `
      <div class="pdf-chapter-item">
        <span class="chap-num">${i+1}</span>
        <span>${c}</span>
      </div>
    `).join('');
  } else {
    html += '<p style="color:var(--text-light)">未提取到章节信息</p>';
  }
  document.getElementById('kpTitle').textContent = '教材详情';
  document.getElementById('kpBody').innerHTML = html;
  document.getElementById('btnMarkLearned').style.display = 'none';
  // 教材阅读器使用宽版弹窗，隐藏底部操作栏
  const modalContent = document.querySelector('#knowledgeModal .modal-content');
  if (modalContent) modalContent.classList.add('modal-wide');
  const modalFooter = document.querySelector('#knowledgeModal .modal-footer');
  if (modalFooter) modalFooter.style.display = 'none';
  document.getElementById('knowledgeModal').classList.add('show');
}

// ============ 目录手动编辑器 ============
// 确保教材有 units 结构
function ensureUnits(textbook) {
  if (!textbook.units || !Array.isArray(textbook.units)) {
    textbook.units = [];
  }
  for (const u of textbook.units) {
    if (!u.lessons || !Array.isArray(u.lessons)) u.lessons = [];
  }
  return textbook.units;
}

// 打开目录编辑器
function openTocEditor(textbookId) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t) return;
  ensureUnits(t);
  renderTocEditor(textbookId);
}

function renderTocEditor(textbookId) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t) return;
  const units = t.units;

  let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <h3 style="margin:0;">📑 编辑目录</h3>
    <button class="btn-primary btn-sm" onclick="viewTextbook('${textbookId}')">← 返回阅读</button>
  </div>`;

  html += `<div style="background:#FFF8E1;border:1px solid #FFE082;border-radius:10px;padding:10px 14px;margin-bottom:16px;font-size:13px;color:#795548;">
    💡 手动编辑目录结构：单元（一级）→ 栏目（二级，如阅读/写作）→ 课文（三级，需填页码）。点击"添加"按钮新增，点击"×"删除，直接在输入框修改标题和页码。
  </div>`;

  units.forEach((u, ui) => {
    html += `<div class="toc-edit-unit">`;
    // 单元标题
    html += `<div class="toc-edit-row toc-edit-unit-row">
      <span class="toc-edit-label">单元</span>
      <input class="toc-edit-input" value="${escapeHtml(u.title)}" onchange="tocUpdateUnit('${textbookId}', ${ui}, 'title', this.value)" placeholder="单元标题，如：第一单元">
      <button class="toc-edit-btn del" onclick="tocDeleteUnit('${textbookId}', ${ui})" title="删除单元">×</button>
    </div>`;

    // 栏目和课文
    u.lessons.forEach((l, li) => {
      const isGroup = l.type === 'group';
      html += `<div class="toc-edit-row ${isGroup ? 'toc-edit-group-row' : 'toc-edit-lesson-row'}">
        <span class="toc-edit-label">${isGroup ? '栏目' : '课文'}</span>
        <input class="toc-edit-input" value="${escapeHtml(l.title)}" onchange="tocUpdateLesson('${textbookId}', ${ui}, ${li}, 'title', this.value)" placeholder="${isGroup ? '栏目名，如：阅读' : '课文名，如：1 春'}">
        ${isGroup ? '' : `<input class="toc-edit-input toc-edit-page" type="number" min="1" value="${l.startPage || ''}" onchange="tocUpdateLesson('${textbookId}', ${ui}, ${li}, 'startPage', this.value)" placeholder="页码">`}
        <button class="toc-edit-btn type" onclick="tocToggleLessonType('${textbookId}', ${ui}, ${li})" title="切换栏目/课文">${isGroup ? '📖' : '📁'}</button>
        <button class="toc-edit-btn del" onclick="tocDeleteLesson('${textbookId}', ${ui}, ${li})" title="删除">×</button>
      </div>`;
    });

    // 添加按钮
    html += `<div class="toc-edit-add-row">
      <button class="btn-secondary btn-sm" onclick="tocAddLesson('${textbookId}', ${ui}, 'group')">+ 栏目</button>
      <button class="btn-secondary btn-sm" onclick="tocAddLesson('${textbookId}', ${ui}, 'lesson')">+ 课文</button>
    </div>`;
    html += `</div>`;
  });

  // 添加单元
  html += `<button class="btn-primary" style="width:100%;margin-top:12px;" onclick="tocAddUnit('${textbookId}')">+ 添加单元</button>`;

  // 操作按钮
  html += `<div style="display:flex;gap:10px;margin-top:16px;">
    <button class="btn-primary" style="flex:1;" onclick="tocSave('${textbookId}')">✓ 保存目录</button>
    <button class="btn-secondary" style="flex:1;" onclick="tocAutoExtract('${textbookId}')">🔄 重新自动提取</button>
  </div>`;

  document.getElementById('kpTitle').textContent = '编辑目录';
  document.getElementById('kpBody').innerHTML = html;
}

// 单元操作
function tocAddUnit(textbookId) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t) return;
  ensureUnits(t);
  t.units.push({ title: '新单元', lessons: [] });
  saveData(state);
  renderTocEditor(textbookId);
}

function tocDeleteUnit(textbookId, ui) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t) return;
  t.units.splice(ui, 1);
  saveData(state);
  renderTocEditor(textbookId);
}

function tocUpdateUnit(textbookId, ui, field, value) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t || !t.units[ui]) return;
  t.units[ui][field] = value;
  saveData(state);
}

// 课文/栏目操作
function tocAddLesson(textbookId, ui, type) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t || !t.units[ui]) return;
  const newItem = type === 'group' 
    ? { title: '新栏目', type: 'group' }
    : { title: '新课文', type: 'lesson', startPage: 1 };
  t.units[ui].lessons.push(newItem);
  saveData(state);
  renderTocEditor(textbookId);
}

function tocDeleteLesson(textbookId, ui, li) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t || !t.units[ui]) return;
  t.units[ui].lessons.splice(li, 1);
  saveData(state);
  renderTocEditor(textbookId);
}

function tocUpdateLesson(textbookId, ui, li, field, value) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t || !t.units[ui] || !t.units[ui].lessons[li]) return;
  if (field === 'startPage') value = parseInt(value) || 0;
  t.units[ui].lessons[li][field] = value;
  saveData(state);
}

function tocToggleLessonType(textbookId, ui, li) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t || !t.units[ui] || !t.units[ui].lessons[li]) return;
  const l = t.units[ui].lessons[li];
  if (l.type === 'group') {
    l.type = 'lesson';
    l.startPage = l.startPage || 1;
  } else {
    l.type = 'group';
    delete l.startPage;
    delete l.endPage;
  }
  saveData(state);
  renderTocEditor(textbookId);
}

// 保存并返回阅读页
async function tocSave(textbookId) {
  // 重新计算 endPage
  const t = state.textbooks.find(x => x.id === textbookId);
  if (t) {
    const allLessons = [];
    t.units.forEach(u => u.lessons.forEach(l => { if (l.type === 'lesson') allLessons.push(l); }));
    for (let i = 0; i < allLessons.length; i++) {
      const next = i + 1 < allLessons.length ? (allLessons[i + 1].startPage || 1) : 9999;
      allLessons[i].endPage = Math.max(allLessons[i].startPage || 1, next - 1);
    }
    saveData(state);

    // 把用户手动编辑的目录也写回 PDF 书签
    if (t.hasPdf && t.units.some(u => u.lessons.some(l => l.type === 'lesson'))) {
      try {
        const arrayBuffer = await loadPdfFromDB(textbookId);
        if (arrayBuffer) {
          const modified = await addBookmarksToPdf(arrayBuffer, t.units);
          await savePdfToDB(textbookId, modified, t.name);
          if (_pdfDocCache[textbookId]) {
            try { _pdfDocCache[textbookId].destroy(); } catch(e) {}
            delete _pdfDocCache[textbookId];
          }
        }
      } catch (e) {
        console.warn('[目录保存] 写回书签失败:', e);
      }
    }
  }
  showToast('目录已保存');
  viewTextbook(textbookId);
}

// 重新自动提取（需重新解析 PDF）
async function tocAutoExtract(textbookId) {
  const t = state.textbooks.find(x => x.id === textbookId);
  if (!t) return;
  if (!t.hasPdf) {
    showToast('该教材没有 PDF 文件，无法自动提取');
    return;
  }
  showToast('正在重新提取目录...');
  try {
    const arrayBuffer = await loadPdfFromDB(textbookId);
    if (!arrayBuffer) {
      showToast('PDF 文件已丢失，请重新上传');
      return;
    }
    const data = new Uint8Array(arrayBuffer.slice(0));
    const pdf = await pdfjsLib.getDocument({ data }).promise;
    // 提取文本
    const pageTexts = [];
    let fullText = '';
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const textContent = await page.getTextContent();
      const lines = [];
      const yMap = {};
      for (const item of textContent.items) {
        const y = Math.round(item.transform[5]);
        let lineKey = y;
        for (const key of Object.keys(yMap)) {
          if (Math.abs(parseInt(key) - y) <= 3) { lineKey = parseInt(key); break; }
        }
        if (!yMap[lineKey]) yMap[lineKey] = [];
        yMap[lineKey].push({ x: item.transform[4], str: item.str });
      }
      const sortedYs = Object.keys(yMap).map(Number).sort((a, b) => b - a);
      for (const y of sortedYs) {
        const line = yMap[y].sort((a, b) => a.x - b.x).map(it => it.str).join('').trim();
        if (line) lines.push(line);
      }
      pageTexts.push(lines.join('\n'));
      fullText += lines.join('\n') + '\n\n';
    }
    // 提取目录
    let units;
    let hadOutline = false;
    try {
      const outline = await pdf.getOutline();
      if (outline && outline.length > 0) {
        hadOutline = true;
        units = await extractUnitsFromOutline(pdf, outline, pdf.numPages);
      }
    } catch (e) {}
    const hasLessons = units && units.length > 0 && units.some(u => u.lessons.some(l => l.type === 'lesson'));
    if (!hasLessons) {
      units = extractLessonsWithPages(fullText, pageTexts, pdf.numPages);
    }
    const hasLessons2 = units && units.length > 0 && units.some(u => u.lessons.some(l => l.type === 'lesson'));
    if (!hasLessons2) {
      units = extractUnitsFromContent(pageTexts, pdf.numPages);
    }
    t.units = units;
    saveData(state);

    // 写回书签
    if (!hadOutline && units && units.some(u => u.lessons.some(l => l.type === 'lesson'))) {
      const modified = await addBookmarksToPdf(arrayBuffer, units);
      await savePdfToDB(textbookId, modified, t.name);
      // 清除 PDF.js 缓存
      if (_pdfDocCache[textbookId]) {
        try { _pdfDocCache[textbookId].destroy(); } catch(e) {}
        delete _pdfDocCache[textbookId];
      }
    }

    showToast(`重新提取完成：${units.length} 个单元`);
    renderTocEditor(textbookId);
  } catch (err) {
    console.error(err);
    showToast('提取失败：' + (err.message || '未知错误'));
  }
}

// PDF 处理
function handlePdfUpload(file) {
  if (!file) return;
  currentPdfData = { name: file.name, size: file.size, chapters: [], arrayBuffer: null, pageTexts: [] };

  document.getElementById('pdfStatus').textContent = '正在读取 PDF...';
  document.getElementById('pdfProgressFill').style.width = '10%';
  document.getElementById('pdfExtracted').hidden = true;
  document.getElementById('btnPdfSave').disabled = true;
  document.getElementById('pdfModal').classList.add('show');

  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const arrayBuffer = e.target.result;
      // 保存原始 buffer 用于后续存入 IndexedDB
      currentPdfData.arrayBuffer = arrayBuffer;
      // 给 PDF.js 传一份副本，避免原始 buffer 被 detach 后无法存入 IndexedDB
      const data = new Uint8Array(arrayBuffer.slice(0));
      document.getElementById('pdfStatus').textContent = '正在解析 PDF...';
      document.getElementById('pdfProgressFill').style.width = '40%';

      const pdf = await pdfjsLib.getDocument({ data }).promise;
      document.getElementById('pdfStatus').textContent = `共 ${pdf.numPages} 页，正在提取文本...`;

      // 按页提取文本，按行组织（根据 y 坐标分行），同时记录每页在全文中的起始字符位置
      const pageTexts = [];
      let fullText = '';
      const pageStartOffsets = [];
      for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i);
        const textContent = await page.getTextContent();
        // 按 y 坐标分行（误差 2px 内视为同一行）
        const lines = [];
        const yMap = {};
        for (const item of textContent.items) {
          const y = Math.round(item.transform[5]);
          let lineKey = y;
          // 查找相近的 y
          for (const key of Object.keys(yMap)) {
            if (Math.abs(parseInt(key) - y) <= 3) { lineKey = parseInt(key); break; }
          }
          if (!yMap[lineKey]) yMap[lineKey] = [];
          yMap[lineKey].push({ x: item.transform[4], str: item.str });
        }
        // 按 y 降序（从上到下），每行内按 x 升序
        const sortedYs = Object.keys(yMap).map(Number).sort((a, b) => b - a);
        for (const y of sortedYs) {
          const lineItems = yMap[y].sort((a, b) => a.x - b.x);
          const line = lineItems.map(it => it.str).join('').trim();
          if (line) lines.push(line);
        }
        const pageText = lines.join('\n');
        pageStartOffsets.push(fullText.length);
        pageTexts.push(pageText);
        fullText += pageText + '\n\n';
        document.getElementById('pdfProgressFill').style.width = (40 + (i / pdf.numPages) * 50) + '%';
      }

      // 统一提取方案：优先 PDF 书签 → 目录页文本 → 全文扫描
      let units;
      let hadOutline = false;
      try {
        const outline = await pdf.getOutline();
        console.log('[目录解析] PDF 书签:', outline ? outline.length + ' 个顶级节点' : '无');
        if (outline && outline.length > 0) {
          hadOutline = true;
          units = await extractUnitsFromOutline(pdf, outline, pdf.numPages);
        }
      } catch (e) {
        console.warn('[目录解析] 获取书签失败:', e);
      }
      // 回退条件：没有可点击课文
      const hasLessons = units && units.length > 0 && units.some(u => u.lessons.some(l => l.type === 'lesson'));
      if (!hasLessons) {
        console.log('[目录解析] 书签无课文，尝试目录页文本提取');
        units = extractLessonsWithPages(fullText, pageTexts, pdf.numPages);
      }
      // 再次检查，如果目录页提取也不行，用全文扫描
      const hasLessons2 = units && units.length > 0 && units.some(u => u.lessons.some(l => l.type === 'lesson'));
      if (!hasLessons2) {
        console.log('[目录解析] 目录页提取失败，尝试全文扫描');
        units = extractUnitsFromContent(pageTexts, pdf.numPages);
      }
      // 最终兜底
      if (!units || units.length === 0 || !units.some(u => u.lessons.some(l => l.type === 'lesson'))) {
        units = [{ title: '教材内容', lessons: [{ title: '教材全文', content: fullText, startPage: 1, endPage: totalPages, type: 'lesson' }] }];
      }

      // 如果 PDF 原本没有书签，但我们提取到了结构，把结构写回 PDF 书签
      let modifiedBuffer = arrayBuffer;
      if (!hadOutline && units.length > 0 && units.some(u => u.lessons.some(l => l.type === 'lesson'))) {
        document.getElementById('pdfStatus').textContent = '正在写入 PDF 书签...';
        modifiedBuffer = await addBookmarksToPdf(arrayBuffer, units);
        currentPdfData.arrayBuffer = modifiedBuffer;
      }

      const chapters = extractChapters(fullText);
      const sections = extractSections(fullText);

      currentPdfData.chapters = chapters;
      currentPdfData.sections = sections;
      currentPdfData.units = units;
      currentPdfData.fullText = fullText;
      currentPdfData.pageTexts = pageTexts;

      const totalLessons = units.reduce((s, u) => s + u.lessons.length, 0);
      document.getElementById('pdfStatus').textContent = `提取完成！识别到 ${units.length} 个单元、${totalLessons} 篇课文`;
      document.getElementById('pdfProgressFill').style.width = '100%';

      if (chapters.length > 0) {
        document.getElementById('pdfExtracted').hidden = false;
        document.getElementById('pdfChapters').innerHTML = chapters.slice(0, 30).map((c, i) => `
          <div class="pdf-chapter-item">
            <span class="chap-num">${i+1}</span>
            <span>${c}</span>
          </div>
        `).join('');
      }
      document.getElementById('btnPdfSave').disabled = false;
    } catch (err) {
      console.error(err);
      document.getElementById('pdfStatus').textContent = '解析失败：该 PDF 可能是扫描版，需 OCR 识别';
      document.getElementById('pdfProgressFill').style.width = '100%';
    }
  };
  reader.readAsArrayBuffer(file);
}

// 从文本中提取章节标题
function extractChapters(text) {
  const patterns = [
    /第[一二三四五六七八九十百零\d]+章[^\n]*/g,
    /第[一二三四五六七八九十百零\d]+单元[^\n]*/g,
    /第[一二三四五六七八九十百零\d]+课[^\n]*/g,
    /第[一二三四五六七八九十百零\d]+节[^\n]*/g,
    /^[一二三四五六七八九十]+[、.．][^\n]*/gm,
    /^\d+[、.．][^\n]*/gm,
  ];
  const found = new Set();
  patterns.forEach(p => {
    const matches = text.match(p);
    if (matches) matches.forEach(m => {
      const clean = m.trim().substring(0, 60);
      if (clean.length > 3) found.add(clean);
    });
  });
  return Array.from(found).slice(0, 50);
}

// 从文本中提取章节及其正文内容
function extractSections(text) {
  // 匹配章节标题的正则（第X章/单元/课/节）
  const headingRegex = /第[一二三四五六七八九十百零\d]+(?:章|单元|课|节)[^\n]*/g;
  const matches = [];
  let m;
  while ((m = headingRegex.exec(text)) !== null) {
    const title = m[0].trim().substring(0, 60);
    if (title.length > 3) {
      matches.push({ index: m.index, title });
    }
  }
  // 按出现位置排序
  matches.sort((a, b) => a.index - b.index);
  // 去重（同一位置的标题只保留一个）
  const unique = [];
  const seenIdx = new Set();
  for (const h of matches) {
    if (!seenIdx.has(h.index)) {
      seenIdx.add(h.index);
      unique.push(h);
    }
  }
  // 提取每个章节的正文
  const sections = [];
  for (let i = 0; i < unique.length; i++) {
    const start = unique[i].index;
    const end = i + 1 < unique.length ? unique[i + 1].index : text.length;
    const content = text.substring(start, end).trim();
    if (content.length > 20) {
      sections.push({ title: unique[i].title, content });
    }
  }
  // 如果没有匹配到章节标题，尝试按"一、""1."等序号切分
  if (sections.length === 0) {
    const subRegex = /^[一二三四五六七八九十]+[、.．][^\n]*$/gm;
    const subMatches = [];
    let sm;
    while ((sm = subRegex.exec(text)) !== null) {
      const title = sm[0].trim().substring(0, 60);
      if (title.length > 2) {
        subMatches.push({ index: sm.index, title });
      }
    }
    subMatches.sort((a, b) => a.index - b.index);
    for (let i = 0; i < subMatches.length; i++) {
      const start = subMatches[i].index;
      const end = i + 1 < subMatches.length ? subMatches[i + 1].index : text.length;
      const content = text.substring(start, end).trim();
      if (content.length > 20) {
        sections.push({ title: subMatches[i].title, content });
      }
    }
  }
  return sections;
}

// 按"单元"组织教材内容，返回 [{title, lessons:[{title,content}]}]
function extractUnits(text) {
  // 1. 匹配单元级标题：第X单元/章/节
  const unitRegex = /第[一二三四五六七八九十百零\d]+(?:单元|章|节)[^\n]*/g;
  // 匹配课文标题：第X课，或行首的"数字 课文名"格式（如"1 春"、"3* 雨的四季"）
  const lessonRegex = /(?:^|\n)(?:第[一二三四五六七八九十百零\d]+课[^\n]*|\d+\*?\s+[\u4e00-\u9fa5][^\n]{1,40})/g;

  const headings = [];
  let um;
  while ((um = unitRegex.exec(text)) !== null) {
    const title = um[0].trim().substring(0, 60);
    if (title.length > 2) headings.push({ index: um.index, title, type: 'unit' });
  }
  let lm;
  while ((lm = lessonRegex.exec(text)) !== null) {
    let title = lm[0].trim().substring(0, 60);
    // 去掉开头的换行符
    title = title.replace(/^\n/, '').trim();
    // 过滤掉纯数字行（页码）和过短的标题
    if (title.length > 2 && !/^\d+$/.test(title)) {
      // 过滤掉明显是目录的行（包含多个页码和斜杠）
      if (!(/\/\s*\d+\s+\d+\//.test(title) || /\d+\s+\d+\s+\d+/.test(title))) {
        headings.push({ index: lm.index + (lm[0].startsWith('\n') ? 1 : 0), title, type: 'lesson' });
      }
    }
  }
  headings.sort((a, b) => a.index - b.index);

  // 去重（同一位置只保留一个，优先 unit）
  const unique = [];
  const seenIdx = new Set();
  for (const h of headings) {
    if (!seenIdx.has(h.index)) {
      seenIdx.add(h.index);
      unique.push(h);
    }
  }
  // 移除 index 非常接近的重复标题（相差 < 3 视为重复，保留先出现的）
  const filtered = [];
  for (const h of unique) {
    if (filtered.length === 0 || h.index - filtered[filtered.length-1].index >= 3) {
      filtered.push(h);
    }
  }

  // 2. 如果有单元级标题，按单元分组；否则全部归入一个默认单元
  const hasUnit = filtered.some(h => h.type === 'unit');
  const units = [];

  if (hasUnit) {
    let curUnit = null;
    for (let i = 0; i < filtered.length; i++) {
      const h = filtered[i];
      const nextIdx = i + 1 < filtered.length ? filtered[i + 1].index : text.length;
      const content = text.substring(h.index, nextIdx).trim();
      if (h.type === 'unit') {
        curUnit = { title: h.title, lessons: [] };
        units.push(curUnit);
      } else {
        if (!curUnit) { curUnit = { title: '教材内容', lessons: [] }; units.push(curUnit); }
        if (content.length > 5) curUnit.lessons.push({ title: h.title, content });
      }
    }
  } else {
    // 没有单元/章/节，全部课文归入"教材内容"
    const curUnit = { title: '教材内容', lessons: [] };
    for (let i = 0; i < filtered.length; i++) {
      const h = filtered[i];
      const nextIdx = i + 1 < filtered.length ? filtered[i + 1].index : text.length;
      const content = text.substring(h.index, nextIdx).trim();
      if (content.length > 5) curUnit.lessons.push({ title: h.title, content });
    }
    units.push(curUnit);
  }

  return units.filter(u => u.lessons.length > 0);
}

// 从 PDF 内置书签（outline）构建三级目录
// 一级：outline 顶级节点 → 单元
// 二级：子节点（无文章编号）→ 栏目
// 三级：子节点（有文章编号）→ 文章
async function extractUnitsFromOutline(pdf, outline, totalPages) {
  const units = [];
  const pageCache = new Map();

  // 解析 dest 获取页码（1-based）
  async function getPageFromDest(dest) {
    if (!dest) return 0;
    let destArray = dest;
    if (typeof dest === 'string') {
      try { destArray = await pdf.getDestination(dest); } catch(e) { return 0; }
    }
    if (!Array.isArray(destArray) || destArray.length === 0) return 0;
    const ref = destArray[0];
    if (pageCache.has(ref)) return pageCache.get(ref);
    try {
      const pageIndex = await pdf.getPageIndex(ref);
      const pageNum = pageIndex + 1;
      pageCache.set(ref, pageNum);
      return pageNum;
    } catch(e) { return 0; }
  }

  // 栏目关键词
  const groupKeywords = ['阅读', '写作', '任务', '综合性学习', '课外古诗词', '名著导读', '口语交际', '活动·探究', '诵读'];
  // 跳过非内容的顶级标题
  const skipTopTitles = ['封面', '目录', '附录', '前言', '后记', '版权页', '扉页', '编者', '编写'];

  // 判断节点是否是栏目：匹配栏目关键词，或有子节点
  const isGroupNode = (node) => {
    const t = (node.title || '').trim();
    const hasKeyword = groupKeywords.some(kw => t === kw || t.startsWith(kw));
    return hasKeyword || (node.items && node.items.length > 0);
  };

  // 遍历顶级节点
  for (const topNode of outline) {
    const topTitle = (topNode.title || '').trim();
    // 跳过明显非单元的顶级节点（封面、目录等）
    const shouldSkip = skipTopTitles.some(s => topTitle.includes(s)) && !/第[一二三四五六七八九十百零\d]+(?:单元|章|节)/.test(topTitle);
    if (shouldSkip) continue;

    const unit = { title: topTitle, lessons: [] };

    // 遍历二级节点
    const children = topNode.items || [];
    for (const child of children) {
      const childTitle = (child.title || '').trim();
      if (isGroupNode(child)) {
        // 二级是栏目
        unit.lessons.push({ title: childTitle, type: 'group' });
        console.log('[书签] 栏目:', childTitle);
        // 遍历三级节点（文章）
        const grandChildren = child.items || [];
        for (const gc of grandChildren) {
          const pageNum = await getPageFromDest(gc.dest);
          unit.lessons.push({ title: (gc.title || '').trim(), type: 'lesson', startPage: pageNum });
          console.log('[书签] 文章:', gc.title, '→ 第', pageNum, '页');
        }
      } else {
        // 二级是叶子节点 → 文章（没有栏目层）
        const pageNum = await getPageFromDest(child.dest);
        unit.lessons.push({ title: childTitle, type: 'lesson', startPage: pageNum });
        console.log('[书签] 文章:', childTitle, '→ 第', pageNum, '页');
      }
    }

    if (unit.lessons.length > 0) units.push(unit);
  }

  // 清理：移除没有课文的空栏目
  for (const u of units) {
    const cleaned = [];
    for (let i = 0; i < u.lessons.length; i++) {
      const l = u.lessons[i];
      if (l.type === 'group') {
        let hasLessonAfter = false;
        for (let j = i + 1; j < u.lessons.length; j++) {
          if (u.lessons[j].type === 'group') break;
          if (u.lessons[j].type === 'lesson') { hasLessonAfter = true; break; }
        }
        if (hasLessonAfter) cleaned.push(l);
      } else {
        cleaned.push(l);
      }
    }
    u.lessons = cleaned;
  }

  // 计算 endPage
  const allLessons = [];
  units.forEach(u => u.lessons.forEach(l => { if (l.type === 'lesson') allLessons.push(l); }));
  for (let i = 0; i < allLessons.length; i++) {
    const next = i + 1 < allLessons.length ? allLessons[i + 1].startPage : totalPages + 1;
    allLessons[i].endPage = Math.max(allLessons[i].startPage || 1, next - 1);
    if (allLessons[i].endPage > totalPages) allLessons[i].endPage = totalPages;
    if (!allLessons[i].startPage) allLessons[i].startPage = 1;
  }

  console.log('[书签] 最终单元数:', units.length, '文章数:', allLessons.length);
  return units;
}

// 统一课文提取方案：仅从 PDF 目录页解析，处理文本合并行
// 一级：第X单元
// 二级：阅读/写作/任务等栏目
// 三级：数字开头的文章
function extractLessonsWithPages(fullText, pageTexts, totalPages) {
  const norm = s => s.replace(/[，。、；：！？""''（）《》\s,.;:!?'"'()<>*·]/g, '');

  // 1. 找到目录页
  const tocPageIndices = [];
  for (let p = 0; p < pageTexts.length; p++) {
    if (pageTexts[p].includes('目录')) tocPageIndices.push(p);
  }
  const tocSet = new Set(tocPageIndices);
  console.log('[目录解析] 目录页:', tocPageIndices.map(p => p + 1));

  if (tocPageIndices.length === 0) {
    // 没有目录页，回退到简单提取
    return [{ title: '教材内容', lessons: [{ title: '教材全文', content: fullText, startPage: 1, endPage: totalPages, type: 'lesson' }] }];
  }

  // 2. 收集目录页所有文本行
  const tocLines = [];
  for (const pi of tocPageIndices) {
    for (const line of pageTexts[pi].split('\n')) {
      const trimmed = line.trim();
      if (trimmed && trimmed !== '目录') tocLines.push(trimmed);
    }
  }
  console.log('[目录解析] 目录页行数:', tocLines.length);
  console.log('[目录解析] 前30行原始文本:');
  tocLines.slice(0, 30).forEach((l, i) => console.log(`  [${i}] ${l}`));

  // 3. 逐行解析：单元 → 栏目 → 文章
  const units = [];
  let curUnit = null;
  const groupKeywords = ['阅读', '写作', '任务', '综合性学习', '课外古诗词', '名著导读', '口语交际', '活动·探究', '诵读'];
  const unitRegex = /第[一二三四五六七八九十百零\d]+(?:单元|章|节)/;

  for (const line of tocLines) {
    // 检查是否包含单元标题
    const unitMatch = line.match(unitRegex);
    if (unitMatch) {
      const unitEnd = unitMatch.index + unitMatch[0].length;
      const afterUnit = line.substring(unitEnd).trim();
      curUnit = { title: unitMatch[0], lessons: [] };
      units.push(curUnit);

      // 如果单元标题后面紧跟栏目（如"第一单元阅读"），提取栏目
      for (const kw of groupKeywords) {
        if (afterUnit.startsWith(kw)) {
          curUnit.lessons.push({ title: kw, type: 'group' });
          break;
        }
      }
      continue;
    }

    if (!curUnit) continue;

    // 检查是否是栏目行（独立成行的栏目关键词）
    const isGroup = groupKeywords.some(kw => {
      // 栏目行：恰好等于关键词，或以关键词开头后跟冒号
      return line === kw || line.startsWith(kw + '：') || line.startsWith(kw + ':');
    });
    if (isGroup) {
      let groupName = line;
      const colonIdx = line.search(/[：:]/);
      if (colonIdx > 0) groupName = line.substring(0, colonIdx).trim();
      curUnit.lessons.push({ title: groupName, type: 'group' });
      continue;
    }

    // 检查是否是课文行：以数字开头
    const lessonMatch = line.match(/^(\d+)\*?\s*(.+)$/);
    if (lessonMatch) {
      const [, num, rest] = lessonMatch;
      // 去掉引导点（...）和空格
      let title = rest.replace(/[.．·•…]+/g, ' ').replace(/\s+/g, ' ').trim();
      // 去掉末尾的页码（数字）
      title = title.replace(/\s+\d{1,4}$/, '').trim();
      // 去掉作者信息（/ 作者）
      const slashIdx = title.indexOf('/');
      if (slashIdx > 0) title = title.substring(0, slashIdx).trim();
      // 去掉写作任务中的冒号后内容（如"写作：热爱生活" → "热爱生活"）
      // 但保留标题本身

      if (title.length >= 2) {
        const star = line.match(/^\d+\*?/)[0].endsWith('*') ? '*' : '';
        curUnit.lessons.push({
          title: num + star + ' ' + title,
          type: 'lesson',
          _coreTitle: title,
        });
      }
      continue;
    }

    // 其他行忽略
  }

  console.log('[目录解析] 单元数:', units.length);

  // 4. 去重：同一单元内相同标题只保留一个
  for (const u of units) {
    const seen = new Set();
    u.lessons = u.lessons.filter(l => {
      if (l.type !== 'lesson') return true;
      const key = norm(l._coreTitle);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  // 5. 清理：移除没有课文的空栏目
  for (const u of units) {
    const cleaned = [];
    for (let i = 0; i < u.lessons.length; i++) {
      const l = u.lessons[i];
      if (l.type === 'group') {
        // 检查这个栏目后面是否有课文（在下一个栏目或单元之前）
        let hasLessonAfter = false;
        for (let j = i + 1; j < u.lessons.length; j++) {
          if (u.lessons[j].type === 'group') break;
          if (u.lessons[j].type === 'lesson') { hasLessonAfter = true; break; }
        }
        if (hasLessonAfter) cleaned.push(l);
      } else {
        cleaned.push(l);
      }
    }
    u.lessons = cleaned;
  }

  // 6. 为每篇文章定位实际 PDF 页码
  const allLessons = [];
  units.forEach(u => u.lessons.forEach(l => { if (l.type === 'lesson') allLessons.push(l); }));

  for (const l of allLessons) {
    const core = norm(l._coreTitle);
    let actualPage = 0;
    if (core) {
      for (let p = 0; p < pageTexts.length; p++) {
        if (tocSet.has(p)) continue;
        if (norm(pageTexts[p]).includes(core)) {
          actualPage = p + 1;
          break;
        }
      }
    }
    l.startPage = actualPage;
    delete l._coreTitle;
    if (actualPage > 0) console.log('[页码定位]', l.title, '→ 第', actualPage, '页');
  }

  // 7. 移除找不到正文的文章
  for (const u of units) {
    u.lessons = u.lessons.filter(l => l.type === 'group' || l.startPage > 0);
  }

  // 8. 再次清理：移除没有课文的空栏目
  for (const u of units) {
    const cleaned = [];
    for (let i = 0; i < u.lessons.length; i++) {
      const l = u.lessons[i];
      if (l.type === 'group') {
        let hasLessonAfter = false;
        for (let j = i + 1; j < u.lessons.length; j++) {
          if (u.lessons[j].type === 'group') break;
          if (u.lessons[j].type === 'lesson') { hasLessonAfter = true; break; }
        }
        if (hasLessonAfter) cleaned.push(l);
      } else {
        cleaned.push(l);
      }
    }
    u.lessons = cleaned;
  }

  // 9. 计算 endPage
  const validLessons = [];
  units.forEach(u => u.lessons.forEach(l => { if (l.type === 'lesson') validLessons.push(l); }));
  for (let i = 0; i < validLessons.length; i++) {
    const next = i + 1 < validLessons.length ? validLessons[i + 1].startPage : totalPages + 1;
    validLessons[i].endPage = Math.max(validLessons[i].startPage, next - 1);
    if (validLessons[i].endPage > totalPages) validLessons[i].endPage = totalPages;
  }

  // 如果最终没有任何课文，回退到全文
  const result = units.filter(u => u.lessons.some(l => l.type === 'lesson'));
  if (result.length === 0) {
    return [{ title: '教材内容', lessons: [{ title: '教材全文', content: fullText, startPage: 1, endPage: totalPages, type: 'lesson' }] }];
  }

  console.log('[目录解析] 最终单元数:', result.length, '文章数:', validLessons.length);
  return result;
}

// 全文扫描提取：不依赖目录页，直接从所有页面的页眉位置识别单元/栏目/课文
// 优势：目录页格式千奇百怪，但正文页的标题位置通常很规范
function extractUnitsFromContent(pageTexts, totalPages) {
  const units = [];
  let curUnit = null;
  const unitRegex = /^第[一二三四五六七八九十百零\d]+(?:单元|章|节)/;
  const groupKeywords = ['阅读', '写作', '任务', '综合性学习', '课外古诗词', '名著导读', '口语交际', '活动·探究', '诵读'];
  const lessonRegex = /^(\d+)\*?\s+(.+)$/;

  for (let p = 0; p < pageTexts.length; p++) {
    const lines = pageTexts[p].split('\n');
    // 只看每页前 6 行（标题通常在页面顶部）
    const headerLines = lines.slice(0, 6);

    for (const line of headerLines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.length > 40) continue;

      // 单元标题
      if (unitRegex.test(trimmed)) {
        curUnit = { title: trimmed, lessons: [] };
        units.push(curUnit);
        console.log('[全文扫描] 单元:', trimmed, '→ 第', p + 1, '页');
        continue;
      }

      if (!curUnit) continue;

      // 栏目
      const isGroup = groupKeywords.some(kw => trimmed === kw || trimmed.startsWith(kw + '：') || trimmed.startsWith(kw + ':'));
      if (isGroup) {
        let groupName = trimmed;
        const colonIdx = trimmed.search(/[：:]/);
        if (colonIdx > 0) groupName = trimmed.substring(0, colonIdx).trim();
        curUnit.lessons.push({ title: groupName, type: 'group' });
        console.log('[全文扫描] 栏目:', groupName);
        continue;
      }

      // 课文（数字开头）
      const lm = trimmed.match(lessonRegex);
      if (lm) {
        const [, num, rest] = lm;
        let title = rest.replace(/[.．·•…]+/g, ' ').replace(/\s+/g, ' ').trim();
        const slashIdx = title.indexOf('/');
        if (slashIdx > 0) title = title.substring(0, slashIdx).trim();
        if (title.length >= 2 && title.length <= 30) {
          const star = trimmed.match(/^\d+\*?/)[0].endsWith('*') ? '*' : '';
          curUnit.lessons.push({
            title: num + star + ' ' + title,
            type: 'lesson',
            startPage: p + 1,
          });
          console.log('[全文扫描] 课文:', num + star + ' ' + title, '→ 第', p + 1, '页');
        }
      }
    }
  }

  // 清理空栏目
  for (const u of units) {
    const cleaned = [];
    for (let i = 0; i < u.lessons.length; i++) {
      const l = u.lessons[i];
      if (l.type === 'group') {
        let hasLessonAfter = false;
        for (let j = i + 1; j < u.lessons.length; j++) {
          if (u.lessons[j].type === 'group') break;
          if (u.lessons[j].type === 'lesson') { hasLessonAfter = true; break; }
        }
        if (hasLessonAfter) cleaned.push(l);
      } else {
        cleaned.push(l);
      }
    }
    u.lessons = cleaned;
  }

  // 计算 endPage
  const allLessons = [];
  units.forEach(u => u.lessons.forEach(l => { if (l.type === 'lesson') allLessons.push(l); }));
  for (let i = 0; i < allLessons.length; i++) {
    const next = i + 1 < allLessons.length ? allLessons[i + 1].startPage : totalPages + 1;
    allLessons[i].endPage = Math.max(allLessons[i].startPage, next - 1);
    if (allLessons[i].endPage > totalPages) allLessons[i].endPage = totalPages;
  }

  const result = units.filter(u => u.lessons.some(l => l.type === 'lesson'));
  console.log('[全文扫描] 最终单元数:', result.length, '文章数:', allLessons.length);
  return result;
}

// 把提取到的目录结构写入 PDF 书签（outline）
// 这样下次打开 PDF 时，pdf.js 的 getOutline() 就能直接拿到正确的三级结构
async function addBookmarksToPdf(arrayBuffer, units) {
  try {
    if (typeof PDFLib === 'undefined') {
      console.warn('[书签写入] pdf-lib 未加载，跳过');
      return arrayBuffer;
    }
    const pdfDoc = await PDFLib.PDFDocument.load(arrayBuffer);

    // 构建 pdf-lib 的 outline 结构
    const buildOutline = (lessons) => {
      const items = [];
      let i = 0;
      while (i < lessons.length) {
        const l = lessons[i];
        if (l.type === 'group') {
          // 收集这个栏目下的所有课文
          const children = [];
          i++;
          while (i < lessons.length && lessons[i].type === 'lesson') {
            const lesson = lessons[i];
            children.push({
              title: lesson.title,
              pageIndex: Math.max(0, (lesson.startPage || 1) - 1),
              children: [],
            });
            i++;
          }
          const groupPage = children.length > 0 ? children[0].pageIndex : 0;
          items.push({
            title: l.title,
            pageIndex: groupPage,
            children,
          });
        } else {
          items.push({
            title: l.title,
            pageIndex: Math.max(0, (l.startPage || 1) - 1),
            children: [],
          });
          i++;
        }
      }
      return items;
    };

    const outline = units.map(u => {
      const children = buildOutline(u.lessons);
      const firstPage = children.length > 0 ? children[0].pageIndex : 0;
      return {
        title: u.title,
        pageIndex: firstPage,
        children,
      };
    });

    // pdf-lib 的 setOutline（部分版本支持）
    if (typeof pdfDoc.setOutline === 'function') {
      pdfDoc.setOutline(outline);
    } else {
      // 低版本兼容：手动操作 catalog 的 Outlines
      console.warn('[书签写入] pdf-lib 无 setOutline，尝试手动写入');
      const outlines = [];
      const createOutlineItem = (item, parent) => {
        const dict = pdfDoc.context.obj({
          Title: item.title,
          Parent: parent,
        });
        if (item.children && item.children.length > 0) {
          const kids = item.children.map(c => createOutlineItem(c, dict));
          dict.set(PDFLib.PDFName.of('First'), kids[0]);
          dict.set(PDFLib.PDFName.of('Last'), kids[kids.length - 1]);
          dict.set(PDFLib.PDFName.of('Count'), kids.length);
          dict.set(PDFLib.PDFName.of('Kids'), pdfDoc.context.obj(kids));
        }
        // 设置目标页
        if (item.pageIndex >= 0) {
          const page = pdfDoc.getPage(item.pageIndex);
          dict.set(PDFLib.PDFName.of('Dest'), pdfDoc.context.obj([page.ref, PDFLib.PDFName.of('XYZ')]));
        }
        return dict;
      };
      // 简化处理：如果 setOutline 不存在，就放弃（不破坏原文件）
      console.warn('[书签写入] 手动写入未实现，保留原 PDF');
      return arrayBuffer;
    }

    const modifiedBytes = await pdfDoc.save();
    console.log('[书签写入] 成功写入', outline.length, '个单元书签');
    return modifiedBytes;
  } catch (err) {
    console.error('[书签写入] 失败:', err);
    return arrayBuffer; // 失败则返回原文件
  }
}

// 专门从 PDF 目录页解析单元和课文
// 不使用目录页码，直接在正文中搜索课文标题，找到实际 PDF 物理页码
function extractUnitsFromToc(pageTexts, totalPages) {
  // 1. 找到目录页（包含"目录"字样的页面）
  const tocPageIndices = [];
  for (let p = 0; p < pageTexts.length; p++) {
    if (pageTexts[p].includes('目录')) tocPageIndices.push(p);
  }
  if (tocPageIndices.length === 0) {
    console.log('[目录解析] 未找到目录页');
    return null;
  }
  console.log('[目录解析] 找到目录页:', tocPageIndices.map(p => p+1));

  const tocSet = new Set(tocPageIndices);
  const norm = s => s.replace(/[，。、；：！？""''（）《》\s,.;:!?'"'()<>*·]/g, '');

  // 排除关键词：这些不是课文条目（只检查核心标题，不检查整行）
  const excludeKeywords = ['任务', '写作', '名著导读', '综合性学习', '课外古诗词', '诵读', '口语交际', '综合性'];

  // 2. 合并所有目录页的文本行
  const tocLines = [];
  for (const pi of tocPageIndices) {
    const lines = pageTexts[pi].split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed && trimmed !== '目录') tocLines.push(trimmed);
    }
  }
  console.log('[目录解析] 目录页共', tocLines.length, '行文本');

  // 3. 逐行解析：识别单元标题 vs 课文条目
  const units = [];
  let curUnit = null;
  const unitRegex = /^第[一二三四五六七八九十百零\d]+(?:单元|章|节)/;
  // 课文条目：阿拉伯数字课号 + 中文标题 + 可选作者 + 可选页码
  // 放宽匹配：不限制标题长度，只要数字+空格+中文开头即可
  const lessonRegex = /^(\d+)\*?\s+([\u4e00-\u9fa5].*?)(?:\s+\d{1,4})?$/;

  for (const line of tocLines) {
    if (unitRegex.test(line)) {
      // 单元标题
      curUnit = { title: line.substring(0, 60), lessons: [] };
      units.push(curUnit);
      console.log('[目录解析] 新单元:', curUnit.title);
    } else {
      const lm = line.match(lessonRegex);
      if (lm) {
        const [, num, rest] = lm;
        // 去掉作者信息（/ 作者），保留纯标题用于搜索
        const coreTitle = rest.replace(/\s*\/.*$/, '').trim();
        // 排除非课文条目（只检查核心标题）
        const isExcluded = excludeKeywords.some(kw => coreTitle.includes(kw));
        if (coreTitle.length < 2 || isExcluded) continue;
        if (!curUnit) { curUnit = { title: '教材内容', lessons: [] }; units.push(curUnit); }
        const star = line.match(/^\d+\*?/)[0].endsWith('*') ? '*' : '';
        curUnit.lessons.push({
          title: num + star + ' ' + rest,
          content: '',
          _coreTitle: coreTitle,
        });
      }
    }
  }

  console.log('[目录解析] 提取到', units.length, '个单元，共', units.reduce((s,u)=>s+u.lessons.length,0), '篇课文');
  if (units.length === 0) return null;

  // 4. 逐篇搜索正文，找到每篇课文的实际 PDF 物理页码
  const allLessons = [];
  units.forEach(u => u.lessons.forEach(l => allLessons.push(l)));

  for (const l of allLessons) {
    const core = norm(l._coreTitle);
    let actualPage = -1;
    if (core) {
      for (let p = 0; p < pageTexts.length; p++) {
        if (tocSet.has(p)) continue;
        if (norm(pageTexts[p]).includes(core)) {
          actualPage = p + 1;
          break;
        }
      }
    }
    l.startPage = actualPage > 0 ? actualPage : 1;
    delete l._coreTitle;
    console.log('[页码定位]', l.title, '→ PDF 第', l.startPage, '页');
  }

  // 5. 计算每篇课文的结束页码 = 下一篇起始页 - 1
  for (let i = 0; i < allLessons.length; i++) {
    const next = i + 1 < allLessons.length ? allLessons[i + 1].startPage : totalPages + 1;
    allLessons[i].endPage = Math.max(allLessons[i].startPage, next - 1);
    if (allLessons[i].endPage > totalPages) allLessons[i].endPage = totalPages;
  }

  return units.filter(u => u.lessons.length > 0);
}

function closePdfModal() {
  document.getElementById('pdfModal').classList.remove('show');
  currentPdfData = null;
}

function saveTextbook() {
  if (!currentPdfData) return;
  // 尝试匹配学科
  const subject = guessSubject(currentPdfData.name);
  const tid = 't' + Date.now();
  const textbook = {
    id: tid,
    name: currentPdfData.name,
    subject: subject,
    size: currentPdfData.size,
    uploadTime: Date.now(),
    chapters: currentPdfData.chapters || [],
    sections: currentPdfData.sections || [],
    units: currentPdfData.units || [],
    hasPdf: !!currentPdfData.arrayBuffer,
  };
  // 如果没有提取到章节，则把全文作为一个章节保存
  if (textbook.sections.length === 0 && currentPdfData.fullText) {
    textbook.sections = [{ title: '教材全文', content: currentPdfData.fullText }];
  }
  if (textbook.units.length === 0 && currentPdfData.fullText) {
    textbook.units = [{ title: '教材内容', lessons: [{ title: '教材全文', content: currentPdfData.fullText, startPage: 1 }] }];
  }
  state.textbooks.unshift(textbook);
  saveData(state);
  renderTextbooks();
  showToast(`教材已保存${subject ? '（识别为：'+subject+'）' : ''}`);

  // 保存 PDF 原始文件到 IndexedDB（异步，不阻塞 UI）
  // 注意：必须先取出 arrayBuffer 再关闭弹窗，否则 closePdfModal 会清空 currentPdfData
  const pdfBuffer = currentPdfData.arrayBuffer;
  const pdfName = currentPdfData.name;
  if (pdfBuffer) {
    console.log('[教材保存] 正在保存 PDF 到 IndexedDB，大小:', pdfBuffer.byteLength, 'bytes');
    savePdfToDB(tid, pdfBuffer, pdfName).then(() => {
      console.log('[教材保存] PDF 已保存到 IndexedDB:', tid);
      closePdfModal(); // 保存完成后再关闭弹窗并清空数据
    }).catch(err => {
      console.error('[教材保存] PDF 保存失败:', err);
      alert('PDF 文件保存失败：' + err.message);
      closePdfModal(); // 即使失败也关闭弹窗
    });
  } else {
    console.warn('[教材保存] 没有 PDF arrayBuffer，hasPdf 将为 false');
    closePdfModal();
  }
}

function guessSubject(filename) {
  const map = {
    '语文': '语文', '数学': '数学', '英语': '英语', '历史': '历史',
    '地理': '地理', '物理': '物理', '化学': '化学', '道德': '道德与法治',
    '道法': '道德与法治', '政治': '道德与法治'
  };
  for (const key in map) {
    if (filename.includes(key)) return map[key];
  }
  return '';
}

// ============ 设置 ============
function renderSettings() {
  document.getElementById('settingNickname').value = state.nickname;
  document.getElementById('settingDailyGoal').value = state.dailyGoal;
}

function saveSettings() {
  state.nickname = document.getElementById('settingNickname').value.trim() || '安冉';
  state.dailyGoal = parseInt(document.getElementById('settingDailyGoal').value) || 3;
  saveData(state);
  renderAll();
  showToast('设置已保存');
}

function exportData() {
  const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `安冉学习助手数据_${todayStr()}.json`;
  a.click();
  URL.revokeObjectURL(url);
  showToast('数据已导出');
}

// ============ 导航 ============
function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const target = document.getElementById('page-' + page);
  if (target) target.classList.add('active');
  document.querySelectorAll('.tab-item').forEach(t => {
    t.classList.toggle('active', t.dataset.page === page);
  });
  document.querySelector('.content').scrollTop = 0;
}

// ============ 工具函数 ============
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
}

function formatTime(ts) {
  const d = new Date(ts);
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
  if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
  return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + 'B';
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + 'KB';
  return (bytes/1024/1024).toFixed(1) + 'MB';
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ============ 事件监听 ============
function setupEventListeners() {
  // 底部导航
  document.querySelectorAll('.tab-item').forEach(tab => {
    tab.addEventListener('click', () => navigate(tab.dataset.page));
  });

  // 打卡
  document.getElementById('btnDailyCheckin').addEventListener('click', dailyCheckin);

  // 日历导航
  document.getElementById('calPrev').addEventListener('click', () => {
    calMonth--;
    if (calMonth < 0) { calMonth = 11; calYear--; }
    renderCalendar();
  });
  document.getElementById('calNext').addEventListener('click', () => {
    calMonth++;
    if (calMonth > 11) { calMonth = 0; calYear++; }
    renderCalendar();
  });

  // 标记已学
  document.getElementById('btnMarkLearned').addEventListener('click', markLearned);

  // 学习页 tab 切换
  document.querySelectorAll('.learn-tab').forEach(tab => {
    tab.addEventListener('click', () => switchLearnSection(tab.dataset.section));
  });

  // 奖励标签切换
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const tab = btn.dataset.tab;
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      document.getElementById('tab-' + tab).classList.add('active');
    });
  });

  // 心愿
  document.getElementById('btnAddWish').addEventListener('click', openWishModal);
  document.querySelectorAll('#emojiPicker span').forEach(s => {
    s.addEventListener('click', () => {
      document.querySelectorAll('#emojiPicker span').forEach(x => x.classList.remove('selected'));
      s.classList.add('selected');
      selectedWishIcon = s.textContent;
    });
  });

  // PDF 上传
  const uploadZone = document.getElementById('uploadZone');
  const pdfInput = document.getElementById('pdfInput');
  uploadZone.addEventListener('click', (e) => {
    if (e.target.tagName !== 'BUTTON') pdfInput.click();
  });
  pdfInput.addEventListener('change', (e) => {
    if (e.target.files[0]) handlePdfUpload(e.target.files[0]);
  });
  uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('drag');
  });
  uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag'));
  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag');
    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') handlePdfUpload(file);
    else showToast('请上传 PDF 文件');
  });

  // 设置
  document.getElementById('settingNickname').addEventListener('change', saveSettings);
  document.getElementById('settingDailyGoal').addEventListener('change', saveSettings);
  document.getElementById('btnReset').addEventListener('click', () => {
    showConfirm('确定要重置所有数据吗？此操作不可恢复！', () => {
      resetData();
      state = loadData();
      renderAll();
      showToast('数据已重置');
    });
  });
  document.getElementById('btnExport').addEventListener('click', exportData);

  // 点击模态框背景关闭
  document.querySelectorAll('.modal').forEach(m => {
    m.addEventListener('click', (e) => {
      if (e.target === m) m.classList.remove('show');
    });
  });
}

// 启动
document.addEventListener('DOMContentLoaded', init);
