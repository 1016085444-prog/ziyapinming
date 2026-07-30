/* 子牙品命 — 两个页面共用的前端底座。

   八字页与紫微页是两套完全不同的命盘，但外围的东西一模一样：剪贴板兜底、
   提示条、平滑滚动、星场、微信卡、雷达图。这些各存一份的话，改一处 bug
   就得记着改两遍，而漏改的那一遍恰恰是没人测的那个页面。

   加载顺序：common.js → places.js → app.js / ziwei.js。 */

'use strict';

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const svgNS = 'http://www.w3.org/2000/svg';
const svgEl = (tag, attrs) => {
  const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
};

// ── 星场 ─────────────────────────────────────────────────
/* 星场。用固定种子而不是 Math.random：刷新页面星星不该换位置，
   否则每次进站都像换了张背景图，反而显得廉价。 */
function initStarfield(sel) {
  const svg = $(sel || '#starfield');
  if (!svg) return;

  let seed = 20260726;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };

  const W = 100, H = 100, NS = 'http://www.w3.org/2000/svg';
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);

  for (let i = 0; i < 140; i++) {
    const c = document.createElementNS(NS, 'circle');
    const bright = rnd();
    c.setAttribute('cx', (rnd() * W).toFixed(2));
    c.setAttribute('cy', (rnd() * H).toFixed(2));
    c.setAttribute('r', (0.08 + bright * 0.32).toFixed(3));
    c.setAttribute('fill', bright > 0.88 ? '#F0E4C6' : '#CBDCEF');
    c.setAttribute('opacity', (0.16 + bright * 0.62).toFixed(2));
    // 少数亮星缓慢明灭，多了会像圣诞灯
    if (bright > 0.93) {
      c.setAttribute('class', 'twinkle');
      c.style.animationDelay = (rnd() * 6).toFixed(1) + 's';
    }
    svg.append(c);
  }
}

// ── 生日：年月日三段式输入 ─────────────────────────────────

/* 为什么不用 <input type="date">：
   安卓（微信内置浏览器尤其）的原生日期控件普遍只给一个「按月翻页」的
   日历，没有直接选年份的入口。而本站每个访客都要填一个几十年前的日期
   ——1990 年生的人得往前翻四百多次。这不是体验瑕疵，是让人直接放弃填表，
   而填表是整条漏斗的入口。

   改成「年份用数字键盘直接打 + 月日用短下拉」：四位数字两秒打完；月只有
   12 项、日最多 31 项，短列表在各家浏览器上都稳（长列表在微信内核有渲染
   问题，出生地选择器就是为此才改成自绘的）。 */
function initBirthDate() {
  const yEl = $('#by'), mEl = $('#bm'), dEl = $('#bd');
  if (!yEl || !mEl || !dEl) return null;

  const fill = (sel, n, suffix) => {
    const keep = Number(sel.value) || 0;
    sel.innerHTML = '';
    for (let i = 1; i <= n; i++) {
      const o = document.createElement('option');
      o.value = String(i);
      o.textContent = i + suffix;
      sel.append(o);
    }
    // 原值超出新范围时收敛到该月最后一天，而不是跳回 1 日——
    // 选了 31 日再把月份改成 2 月，用户想要的是月末而不是月初。
    sel.value = String(keep ? Math.min(keep, n) : 1);
  };

  fill(mEl, 12, ' 月');

  /* 日数随年月变：闰年 2 月 29 天、小月 30 天。
     Date(y, m, 0) 即「第 m 月的最后一天」，闰年规则由浏览器负责，不用自己判。 */
  function rebuildDays() {
    const y = Number(yEl.value);
    const m = Number(mEl.value) || 1;
    const base = (Number.isInteger(y) && y >= 1900 && y <= 2100) ? y : 2000;
    fill(dEl, new Date(base, m, 0).getDate(), ' 日');
  }
  rebuildDays();

  yEl.addEventListener('change', rebuildDays);
  yEl.addEventListener('input', rebuildDays);
  mEl.addEventListener('change', rebuildDays);

  return {
    /** 读出 {year, month, day}；年份缺失或越界返回 null。 */
    read() {
      const y = Number(yEl.value);
      if (!Number.isInteger(y) || y < 1900 || y > 2100) return null;
      return { year: y, month: Number(mEl.value), day: Number(dEl.value) };
    },
    /** 回填（从 URL 参数带生辰过来时用）。 */
    set(y, m, d) {
      yEl.value = String(y);
      mEl.value = String(m);
      rebuildDays();
      dEl.value = String(d);
    },
  };
}

// ── 微信卡 ───────────────────────────────────────────────

/* 两个页面的微信卡 DOM 完全一样，配置也来自同一个接口。
   返回微信号，供复制按钮取用。 */
async function loadSiteConfig(state) {
  try {
    const cfg = await (await fetch('/api/config')).json();
    state.wechatId = cfg.wechat_id || '';
    $('#wx-id').textContent = state.wechatId;
    $('#wx-offer').textContent = cfg.wechat_offer || '';

    const qr = $('#wx-qr');
    if (cfg.wechat_qr) {
      qr.src = cfg.wechat_qr;
      qr.hidden = false;
      $('#wx-hint').textContent = '手机上长按二维码识别 · 或复制微信号后在微信里搜索';
    } else {
      $('#wx-hint').textContent = '复制微信号后，在微信「添加朋友」里搜索';
    }
  } catch (err) {
    console.warn('配置读取失败：', err);
  }
  return state.wechatId;
}

// ── 剪贴板 ───────────────────────────────────────────────

/* 这类链接绝大多数在微信内置浏览器里打开，而那里的 navigator.clipboard
   时灵时不灵（iOS 尤其），所以兜底路径是主路径而不是摆设。 */
function legacyCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  // iOS 上元素不能真的不可见、字号小于 16px 会触发缩放，
  // 所以用 1px 透明而不是 top:-9999px。
  ta.style.cssText =
    'position:fixed;top:0;left:0;width:1px;height:1px;padding:0;' +
    'border:none;outline:none;opacity:0;font-size:16px';
  ta.contentEditable = 'true';
  ta.readOnly = false;
  document.body.appendChild(ta);

  // iOS Safari / 微信内核只认 Range 选区，单调 select() 拿不到内容
  const range = document.createRange();
  range.selectNodeContents(ta);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  ta.setSelectionRange(0, text.length);

  let ok = false;
  try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
  sel.removeAllRanges();
  document.body.removeChild(ta);
  return ok;
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) { /* 权限被拒或内置浏览器不支持，落到兜底 */ }
  return legacyCopy(text);
}

/* 平滑滚动 + 兜底。
   某些内置浏览器（微信内核尤其）里 behavior:'smooth' 会静默失效，
   什么都不发生。主 CTA 绝不能因此变成死按钮，所以滚完校一次位，
   没到位就直接跳过去。 */
function scrollToEl(el, offset) {
  const top = Math.max(0, el.getBoundingClientRect().top + window.scrollY - (offset || 10));
  try {
    window.scrollTo({ top: top, behavior: 'smooth' });
  } catch (_) {
    window.scrollTo(0, top);
  }
  setTimeout(() => {
    if (Math.abs(window.scrollY - top) > 40) window.scrollTo(0, top);
  }, 550);
}

let toastTimer = null;
function showToast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  requestAnimationFrame(() => t.classList.add('show'));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    t.classList.remove('show');
    setTimeout(() => { t.hidden = true; }, 300);
  }, 2400);
}

// ── 微信引流：两个页面共用的绑定 ───────────────────────────

/* 点问题标签 = 把「命盘摘要 + 问题」整段复制好。
   用户加上微信直接粘贴就能发出第一条消息，省掉「我该说什么」这一步，
   这一步的摩擦正是私域引流最常见的流失点。 */
function initWechat(state) {
  loadSiteConfig(state);

  const ask = async (question) => {
    const msg = state.summary + '\n想问：' + question;
    const ok = await copyText(msg);
    showToast(ok ? '命盘和问题已复制，加微信后直接粘贴发我'
                 : '复制失败，请截图本页发我');
    // 无论复制成不成功都滚过去：复制失败时更需要把联系方式送到眼前
    scrollToEl($('.wechat-card'), 90);
  };

  $('#suggestions').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (chip) ask(chip.textContent);
  });

  $('#copy-wx').addEventListener('click', async () => {
    const ok = await copyText(state.wechatId);
    showToast(ok ? '微信号已复制' : '复制失败：' + state.wechatId);
  });

  /* 「为什么两套体系分数不同」里的追问。

     这一条是整站最好的话头，因为它满足「待定论」的全部条件：问题真实
     （同一个人两个分，任何人都会想问）、答案确实需要两张盘摆在一起看、
     而且不靠制造恐惧。用户带着这个问题过来时，手上已经有两张盘了。 */
  const whyAsk = $('#why-ask');
  if (whyAsk) {
    whyAsk.addEventListener('click', () => {
      ask('我八字和紫微两套盘的评分不太一样，能帮我对一下'
          + '哪几处一致、哪几处相反吗？（两张盘我都排了，一并发你）');
    });
  }

  return ask;
}

// ── 雷达图 ───────────────────────────────────────────────

/* 评分雷达图。轴数按传入的维度数走：八字是五维、紫微是六维，同一份代码。

   半径直接按分数比例走（分数区间 38–96，映射到 38%–96% 半径），不做二次
   拉伸——拉伸会把差距夸大，看着刺激但不诚实。两套评分都归一到同一中位数与
   散布，所以两张图上的同一个数字代表同等的稀有程度，可以并排比较。 */
const RADAR_R = 34;

function renderScores(data) {
  if (!data) return;
  const svg = $('#radar');
  svg.innerHTML = '';

  const dims = Object.keys(data['维度']);
  const pts = dims.map(function (name, i) {
    const rad = ((-90 + i * (360 / dims.length)) * Math.PI) / 180;
    const score = data['维度'][name]['分数'];
    return { name: name, score: score, rad: rad,
             x: 50 + RADAR_R * (score / 100) * Math.cos(rad),
             y: 50 + RADAR_R * (score / 100) * Math.sin(rad) };
  });

  const ring = function (frac) {
    return pts.map(function (p) {
      return (50 + RADAR_R * frac * Math.cos(p.rad)).toFixed(2) + ',' +
             (50 + RADAR_R * frac * Math.sin(p.rad)).toFixed(2);
    }).join(' ');
  };

  // 参考环：40 / 60 / 80 / 100 分
  [0.4, 0.6, 0.8, 1].forEach(function (f) {
    svg.append(svgEl('polygon', {
      class: 'radar-grid', points: ring(f),
      'stroke-opacity': f === 1 ? 0.28 : 0.12,
    }));
  });

  // 轴线
  pts.forEach(function (p) {
    svg.append(svgEl('line', {
      class: 'radar-axis', x1: 50, y1: 50,
      x2: (50 + RADAR_R * Math.cos(p.rad)).toFixed(2),
      y2: (50 + RADAR_R * Math.sin(p.rad)).toFixed(2),
    }));
  });

  svg.append(svgEl('polygon', {
    class: 'radar-area',
    points: pts.map(function (p) { return p.x.toFixed(2) + ',' + p.y.toFixed(2); }).join(' '),
  }));

  pts.forEach(function (p) {
    svg.append(svgEl('circle', { class: 'radar-dot', cx: p.x, cy: p.y, r: 1.5 }));

    // 标签推到轴外侧；左右两侧改变锚点，避免压住图形
    const lr = RADAR_R + 12;
    const lx = 50 + lr * Math.cos(p.rad);
    const ly = 50 + lr * Math.sin(p.rad);
    const anchor = Math.abs(Math.cos(p.rad)) < 0.25
      ? 'middle' : (Math.cos(p.rad) > 0 ? 'start' : 'end');

    const t = svgEl('text', { class: 'radar-label', x: lx, y: ly - 2.2,
                              'text-anchor': anchor });
    t.textContent = p.name;
    svg.append(t);

    const s = svgEl('text', { class: 'radar-score', x: lx, y: ly + 3.4,
                              'text-anchor': anchor });
    s.textContent = p.score;
    svg.append(s);
  });

  // 总述里的 **强调** 转成金色
  $('#score-lead').innerHTML = String(data['总述'] || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  $('#score-note').textContent = data['说明'] || '';

  const box = $('#score-list');
  box.innerHTML = '';
  dims.forEach(function (name) {
    const item = data['维度'][name];
    const d = el('details', 'score-item');
    // 只默认展开最弱一项：那正是用户最想追问的地方
    if (name === data['最弱']) d.open = true;

    const sum = el('summary');
    sum.append(el('span', 'si-name', name));
    sum.append(el('span', 'si-band', item['评级']));
    sum.append(el('span', 'si-score', String(item['分数'])));
    d.append(sum);

    const ul = el('ul');
    item['依据'].forEach(function (w) { ul.append(el('li', null, w)); });
    d.append(ul);
    box.append(d);
  });
}
