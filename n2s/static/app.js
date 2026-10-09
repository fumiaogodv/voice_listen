/* NoteToSpeech 前端逻辑：库列表 + 播放器 + 歌词式文字同步 + 进度上报 */

(function () {
  'use strict';

  const RATES = [1.0, 1.25, 1.5, 2.0];
  const REPORT_INTERVAL = 4000; // 播放中每 4 秒上报进度

  const audio = document.getElementById('audio');
  const fileListEl = document.getElementById('file-list');
  const textListEl = document.getElementById('text-list');
  const playerTitle = document.getElementById('player-title');
  const btnPlay = document.getElementById('btn-play');
  const btnBack = document.getElementById('btn-back');
  const btnFwd = document.getElementById('btn-fwd');
  const btnRate = document.getElementById('btn-rate');
  const btnLocate = document.getElementById('btn-locate');
  const progressBar = document.getElementById('progress-bar');
  const progressFill = document.getElementById('progress-fill');
  const progressDot = document.getElementById('progress-dot');
  const timeCur = document.getElementById('time-cur');
  const timeDur = document.getElementById('time-dur');
  const btnRefresh = document.getElementById('btn-refresh');
  const btnUpload = document.getElementById('btn-upload');
  const fileInput = document.getElementById('file-input');

  let library = [];          // 全部文件摘要
  let current = null;        // 当前文件详情 {id, title, segments, ...}
  let currentSegEls = [];    // 当前文字条目 DOM
  let activeSegIdx = -1;
  let rateIdx = 0;
  let lastReport = 0;
  let reportTimer = null;
  let userInteracted = false; // iOS 自动播放限制：首次播放需点击
  let autoScroll = true;       // 是否自动滚动到当前播放字段（默认跟随）

  // ---------- 工具 ----------
  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return (m < 10 ? '0' + m : m) + ':' + (s < 10 ? '0' + s : s);
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(path + ' -> ' + res.status);
    return res.json();
  }

  // ---------- 侧栏 ----------
  // 记录每个分类节点的展开状态：true=展开，false/未记录=收起
  const expandedCats = {};

  function renderLibrary() {
    // 按 category 层级构建树：tree[一级][二级]... = 文件数组
    // 用嵌套对象表示，叶子是一个数组（文件列表）
    const tree = {};
    library.forEach((f) => {
      const parts = (f.category || '').split('/').filter(Boolean);
      let node = tree;
      parts.forEach((part) => {
        if (!node[part]) node[part] = {};
        node = node[part];
      });
      // node 现在指向文件所属的最深分类节点，用 __files 存文件
      if (!node.__files) node.__files = [];
      node.__files.push(f);
    });

    fileListEl.innerHTML = '';

    // 当前播放文件所属的顶层分类名（用于自动展开）
    let currentTopCat = null;
    if (current) {
      currentTopCat = (current.category || '').split('/').filter(Boolean)[0] || null;
    }

    function renderLevel(node, depth, parentPath) {
      // 先渲染该层级直属的文件
      if (node.__files && node.__files.length) {
        node.__files.forEach((f) => {
          const item = document.createElement('div');
          item.className = 'file-item' + (current && current.id === f.id ? ' active' : '');
          item.dataset.id = f.id;
          item.style.paddingLeft = (12 + depth * 16) + 'px';

          const name = document.createElement('span');
          name.className = 'name';
          name.textContent = f.title;

          const badge = document.createElement('span');
          badge.className = 'badge';
          if (f.status === 'generating') badge.textContent = '转换中…';
          else if (f.status === 'pending') badge.textContent = '排队中';
          else if (f.status === 'failed') badge.textContent = '失败';
          else if (f.finished) badge.textContent = '已听完';
          else if (f.percent > 0) badge.textContent = '已听 ' + f.percent + '%';
          else badge.textContent = '未开始';
          if (f.finished) badge.className += ' done';
          if (f.status === 'generating' || f.status === 'pending') badge.className += ' gen';

          item.appendChild(name);
          item.appendChild(badge);
          item.addEventListener('click', () => openFile(f.id));
          fileListEl.appendChild(item);
        });
      }

      // 再渲染子分类目录（可折叠）
      Object.keys(node)
        .filter((k) => k !== '__files')
        .sort()
        .forEach((key) => {
          const fullPath = parentPath ? parentPath + '/' + key : key;
          // 展开状态：显式展开 或（当前播放文件的顶层分类自动展开）
          const isTop = parentPath === '';
          const isExpanded = expandedCats[fullPath] === true ||
            (isTop && currentTopCat === fullPath);

          const catHead = document.createElement('div');
          catHead.className = 'cat-head';
          catHead.style.paddingLeft = (8 + depth * 16) + 'px';
          const arrow = document.createElement('span');
          arrow.className = 'cat-arrow';
          arrow.textContent = isExpanded ? '▾' : '▸';
          const catName = document.createElement('span');
          catName.className = 'cat-name';
          catName.textContent = key;
          catHead.appendChild(arrow);
          catHead.appendChild(catName);
          catHead.addEventListener('click', () => {
            expandedCats[fullPath] = !isExpanded;
            renderLibrary();
          });
          fileListEl.appendChild(catHead);

          // 展开时渲染子内容
          if (isExpanded) {
            renderLevel(node[key], depth + 1, fullPath);
          }
        });
    }

    if (library.length === 0) {
      fileListEl.innerHTML = '<div class="placeholder">把 .md / .txt 文件放入 notes 目录后点刷新</div>';
    } else {
      renderLevel(tree, 0, '');
    }
  }

  async function loadLibrary() {
    const data = await api('/api/library');
    library = data.files;
    renderLibrary();
  }

  // ---------- 打开文件 ----------
  async function openFile(id, autoplay) {
    try {
      const detail = await api('/api/files/' + id);
      if (detail.status !== 'ready' || !detail.audio_url) {
        // 未就绪：跳过，尝试下一个（连播场景）
        if (autoplay) { nextFile(); return; }
        alert('该文件还在转换中，请稍后再试');
        return;
      }
      current = detail;
      currentSegEls = [];
      activeSegIdx = -1;
      renderLibrary();
      renderText();
      playerTitle.textContent = detail.title;

      audio.src = detail.audio_url;
      timeDur.textContent = fmt(detail.duration);
      // 换源后浏览器会重置 playbackRate，需重新应用当前倍速（连播时保持倍速）
      applyRate();

      // 断点续播：定位到上次位置（iOS 需用户点击后才真正播放）
      const pos = detail.position_sec || 0;
      audio.currentTime = pos;
      userInteracted = false;
      setPlayIcon(false);
      updateProgress(pos);
      updateActiveSeg(pos);

      // 连播场景：自动开始播放（用户已在听，属连续播放）
      if (autoplay) {
        userInteracted = true;
        audio.play().catch((e) => console.error('autoplay failed', e));
      }
    } catch (e) {
      console.error(e);
      if (!autoplay) alert('打开文件失败');
    }
  }

  function renderText() {
    textListEl.innerHTML = '';
    if (!current || !current.segments.length) {
      textListEl.innerHTML = '<div class="placeholder">该文件无内容</div>';
      return;
    }
    current.segments.forEach((seg, i) => {
      const el = document.createElement('div');
      el.className = 'seg';
      el.dataset.idx = i;

      const num = document.createElement('span');
      num.className = 'seg-num';
      num.textContent = '第 ' + (i + 1) + ' 条';

      const body = document.createElement('span');
      body.textContent = seg.text;

      el.appendChild(num);
      el.appendChild(body);
      el.addEventListener('click', () => {
        audio.currentTime = seg.start_sec;
        if (!userInteracted) { userInteracted = true; }
        if (audio.paused) audio.play().catch(() => {});
        updateProgress(seg.start_sec);
        updateActiveSeg(seg.start_sec);
      });
      textListEl.appendChild(el);
      currentSegEls.push(el);
    });
  }

  // ---------- 歌词式同步 ----------
  function findSegIndex(time) {
    if (!current || !current.segments.length) return -1;
    for (let i = 0; i < current.segments.length; i++) {
      const s = current.segments[i];
      if (time >= s.start_sec && time < s.end_sec) return i;
    }
    if (time >= current.segments[current.segments.length - 1].end_sec) {
      return current.segments.length - 1;
    }
    return -1;
  }

  function updateActiveSeg(time) {
    const idx = findSegIndex(time);
    if (idx === activeSegIdx) return;
    if (activeSegIdx >= 0 && currentSegEls[activeSegIdx]) {
      currentSegEls[activeSegIdx].classList.remove('active');
    }
    activeSegIdx = idx;
    if (idx >= 0 && currentSegEls[idx]) {
      currentSegEls[idx].classList.add('active');
      // 仅在「自动跟随」开启时才滚动，避免打断用户翻阅
      if (autoScroll) {
        currentSegEls[idx].scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }
  }

  // 切换「自动跟随」：点一下关（手动浏览），再点一下开（自动拖回）
  function toggleAutoScroll() {
    autoScroll = !autoScroll;
    syncLocateBtn();
    // 重新开启时，立即定位到当前播放字段
    if (autoScroll) {
      locateToActive();
    }
  }

  // 定位到当前播放字段
  function locateToActive() {
    if (activeSegIdx >= 0 && currentSegEls[activeSegIdx]) {
      currentSegEls[activeSegIdx].scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  // 同步按钮视觉状态（开启=高亮，关闭=灰）
  function syncLocateBtn() {
    if (autoScroll) {
      btnLocate.textContent = '跟随中';
      btnLocate.classList.add('on');
    } else {
      btnLocate.textContent = '已锁定';
      btnLocate.classList.remove('on');
    }
  }

  // ---------- 进度条 ----------
  function updateProgress(time) {
    const dur = (current && current.duration) || audio.duration || 0;
    if (!dur) return;
    const pct = Math.min(100, (time / dur) * 100);
    progressFill.style.width = pct + '%';
    progressDot.style.left = pct + '%';
    timeCur.textContent = fmt(time);
    timeDur.textContent = fmt(dur);
  }

  progressBar.addEventListener('click', (e) => {
    if (!current) return;
    const rect = progressBar.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pct * (current.duration || 0);
  });

  // ---------- 播放控制 ----------
  function setPlayIcon(playing) {
    btnPlay.textContent = playing ? '⏸' : '▶';
  }

  function togglePlay() {
    if (!current) return;
    userInteracted = true;
    if (audio.paused) {
      audio.play().catch((e) => console.error('play failed', e));
    } else {
      audio.pause();
    }
  }

  function skip(sec) {
    if (!current) return;
    const dur = current.duration || 0;
    let t = audio.currentTime + sec;
    if (t < 0) t = 0;
    if (t > dur) t = dur;
    audio.currentTime = t;
    updateProgress(t);
    updateActiveSeg(t);
  }

  function cycleRate() {
    rateIdx = (rateIdx + 1) % RATES.length;
    applyRate();
  }

  // 应用当前倍速到 audio 元素（并同步按钮文字）
  function applyRate() {
    audio.playbackRate = RATES[rateIdx];
    btnRate.textContent = RATES[rateIdx].toFixed(2).replace(/\.?0+$/, '') + 'x';
  }

  // ---------- 进度上报 ----------
  function reportProgress(finished, posOverride) {
    if (!current) return;
    // posOverride 用于播放结束等场景，避免 audio.currentTime 已归零
    let pos = posOverride != null ? posOverride : (audio.currentTime || 0);
    // 标记读完时，位置锁定在总时长
    if (finished) pos = current.duration || pos;
    const body = {
      position_sec: pos,
      finished: finished ? 1 : 0,
    };
    navigator.sendBeacon
      ? navigator.sendBeacon('/api/files/' + current.id + '/progress', new Blob([JSON.stringify(body)], { type: 'application/json' }))
      : fetch('/api/files/' + current.id + '/progress', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        }).catch(() => {});
  }

  function startReportTimer() {
    stopReportTimer();
    reportTimer = setInterval(() => {
      if (!audio.paused) reportProgress(false);
    }, REPORT_INTERVAL);
  }
  function stopReportTimer() {
    if (reportTimer) { clearInterval(reportTimer); reportTimer = null; }
  }

  // ---------- 自动连播 ----------
  function nextFile() {
    if (!current) return false;
    // 同文件夹（同 category）下一个文件
    const sameCat = library.filter((f) => f.category === current.category);
    let idx = sameCat.findIndex((f) => f.id === current.id);
    // 从下一个开始找，优先找未听完的
    for (let i = idx + 1; i < sameCat.length; i++) {
      if (!sameCat[i].finished) {
        openFile(sameCat[i].id, true); // 连播自动播放
        return true;
      }
    }
    // 同文件夹全部听完：停止
    setPlayIcon(false);
    playerTitle.textContent = (current ? current.title : '') + '（本文件夹已全部播完）';
    return false;
  }

  // ---------- 事件绑定 ----------
  audio.addEventListener('timeupdate', () => {
    updateProgress(audio.currentTime);
    const idx = findSegIndex(audio.currentTime);
    // 每条播放完（segment 切换）就更新一次进度，避免"播完还显示0"
    if (idx !== activeSegIdx) {
      updateActiveSeg(audio.currentTime);
      if (idx > 0 && userInteracted) {
        reportProgress(false, audio.currentTime);
      }
    }
  });

  audio.addEventListener('play', () => { setPlayIcon(true); startReportTimer(); });
  audio.addEventListener('pause', () => {
    setPlayIcon(false);
    stopReportTimer();
    if (userInteracted) reportProgress(false);
  });

  audio.addEventListener('ended', () => {
    reportProgress(true); // 标记读完（reportProgress 内部会把位置锁定为总时长）
    if (current) { current.finished = true; current.percent = 100; renderLibrary(); }
    nextFile();
  });

  audio.addEventListener('loadedmetadata', () => {
    if (current && current.duration) timeDur.textContent = fmt(current.duration);
  });

  btnPlay.addEventListener('click', togglePlay);
  btnBack.addEventListener('click', () => skip(-10));
  btnFwd.addEventListener('click', () => skip(10));
  btnRate.addEventListener('click', cycleRate);
  btnLocate.addEventListener('click', toggleAutoScroll);
  btnRefresh.addEventListener('click', async () => {
    await api('/api/scan', { method: 'POST' });
    await loadLibrary();
  });

  // ---------- 上传 ----------
  btnUpload.addEventListener('click', () => {
    fileInput.click();
  });

  fileInput.addEventListener('change', async () => {
    const files = fileInput.files;
    if (!files || files.length === 0) return;

    // 询问目标子目录（可留空表示直接放 notes 根目录）
    const targetDir = prompt(
      '上传到哪个子目录？（留空则放入根目录）\n例如：操作系统/第一章 进程管理\n或直接输入新分类名，会自动创建文件夹',
      ''
    );
    if (targetDir === null) { fileInput.value = ''; return; } // 用户取消

    const form = new FormData();
    for (const f of files) {
      form.append('files', f);
    }
    form.append('target_dir', (targetDir || '').trim());

    try {
      const res = await fetch('/api/upload', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '上传失败');

      let msg = `已上传 ${data.saved.length} 个文件`;
      if (data.skipped.length > 0) {
        msg += `\n跳过 ${data.skipped.length} 个：` +
          data.skipped.map((s) => s.name + '（' + s.reason + '）').join('、');
      }
      alert(msg);
      await loadLibrary();
    } catch (e) {
      alert('上传失败：' + e.message);
    } finally {
      fileInput.value = ''; // 清空，允许重复选同一文件
    }
  });

  // 关闭/切后台时补报进度（锁屏后定时器冻结，必须依赖事件）
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && current && userInteracted) {
      reportProgress(false);
    }
  });
  window.addEventListener('pagehide', () => {
    if (current && userInteracted) reportProgress(false);
  });

  // 键盘快捷键
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
    else if (e.code === 'ArrowLeft') skip(-10);
    else if (e.code === 'ArrowRight') skip(10);
  });

  // 移动端菜单按钮
  const menuBtn = document.createElement('button');
  menuBtn.id = 'menu-toggle';
  menuBtn.textContent = '☰';
  menuBtn.addEventListener('click', () => document.getElementById('sidebar').classList.toggle('open'));
  document.body.appendChild(menuBtn);

  // 点击文字区关闭移动端抽屉
  document.getElementById('text-area').addEventListener('click', () => {
    document.getElementById('sidebar').classList.remove('open');
  });

  // ---------- 启动 ----------
  syncLocateBtn(); // 初始化按钮状态
  loadLibrary().catch(console.error);
  setInterval(() => { if (!current) loadLibrary().catch(() => {}); }, 15000); // 无选择时轮询状态
})();
