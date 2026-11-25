/* 子牙财鉴 —— 页面逻辑。

   依赖 /shared/common.js（$、el、svgEl、剪贴板兜底、提示条、平滑滚动、
   生日三段输入、微信卡）与 /shared/places.js（出生地选择器）。这两份与
   主站共用同一个文件，不复制——城市表与剪贴板兜底只该有一处定义。 */

'use strict';

const state = { wechatId: '', summary: '', nick: '' };

// 推演停顿。算盘本身几毫秒就完，秒出结果像查表，反而折损可信度。
const CAST_STEPS = ['排定八字四柱…', '真太阳时校正…', '安紫微十二宫…',
                    '推演财星与财库…', '双盘合参，测算财富指数…'];
const CAST_MS = 2600;

// ── 金尘 ─────────────────────────────────────────────────
/* 固定种子：刷新页面金尘不该换位置和节奏，否则像每次换了张背景。
   数量刻意少——多了像撒金粉的廉价特效。 */
function initDust() {
  const box = $('#dust');
  if (!box) return;
  let seed = 8888;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < 26; i++) {
    const d = document.createElement('i');
    const size = 1.5 + rnd() * 2.8;
    d.style.left = (rnd() * 100).toFixed(1) + '%';
    d.style.width = d.style.height = size.toFixed(1) + 'px';
    d.style.animationDuration = (14 + rnd() * 16).toFixed(1) + 's';
    d.style.animationDelay = (-rnd() * 30).toFixed(1) + 's';
    d.style.setProperty('--dx', ((rnd() - 0.5) * 120).toFixed(0) + 'px');
    box.append(d);
  }
}

// ── 表单 ─────────────────────────────────────────────────
function readForm(dateInput) {
  const f = $('#birth-form');
  const date = dateInput.read();
  if (!date) return { error: '请填写四位数的出生年份（1900–2100）' };
  const t = (f.time.value || '').split(':');
  if (t.length < 2) return { error: '请填写出生时刻' };
  const place = ZiyaPlaces.selected();
  return {
    payload: {
      year: date.year, month: date.month, day: date.day,
      hour: Number(t[0]), minute: Number(t[1]),
      gender: f.querySelector('input[name=gender]:checked').value,
      longitude: place.longitude, tz_offset: place.tz,
      use_true_solar_time: f.tst.checked,
      late_zi_shifts_day: f.latezi.checked,
      adjust_china_dst: f.dst.checked,
    },
    place: place.name,
  };
}

function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function cast(payload) {
  const box = $('#casting'), step = $('#cast-step'), bar = $('#cast-bar');
  box.hidden = false;
  document.body.classList.add('sheet-open');
  bar.style.width = '0';
  let i = 0;
  step.textContent = CAST_STEPS[0];
  const timer = setInterval(() => {
    i = Math.min(i + 1, CAST_STEPS.length - 1);
    step.textContent = CAST_STEPS[i];
    bar.style.width = ((i + 1) / CAST_STEPS.length * 100) + '%';
  }, CAST_MS / CAST_STEPS.length);
  requestAnimationFrame(() => { bar.style.width = (100 / CAST_STEPS.length) + '%'; });

  try {
    const [res] = await Promise.all([
      fetch('/api/wealth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
      wait(CAST_MS),
    ]);
    if (!res.ok) {
      let msg = '测算失败，请检查输入';
      try { const j = await res.json(); if (typeof j.detail === 'string') msg = j.detail; } catch (_) {}
      throw new Error(msg);
    }
    return await res.json();
  } finally {
    clearInterval(timer);
    box.hidden = true;
    document.body.classList.remove('sheet-open');
  }
}

// ── 渲染：金卡 ───────────────────────────────────────────
function countUp(node, to, ms) {
  const start = performance.now();
  const tick = (now) => {
    const k = Math.min(1, (now - start) / ms);
    const eased = 1 - Math.pow(1 - k, 3);
    node.textContent = String(Math.round(to * eased));
    if (k < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function renderCard(data, payload) {
  const r = data.report;
  $('#vc-tier').textContent = r['品阶']['品阶'];
  $('#vc-owner').textContent = (state.nick ? state.nick + ' · ' : '') + '财富命格';
  $('#vc-rank-name').textContent = r['品阶']['名号'];
  $('#vc-type').textContent = r['类型']['名称'];

  const tags = $('#vc-tags');
  tags.innerHTML = '';
  r['关键词'].forEach((k) => tags.append(el('span', null, k)));

  const pad = (n) => String(n).padStart(2, '0');
  $('#vc-no').textContent = 'NO.' + payload.year + '·' + pad(payload.month) + '·' + pad(payload.day);

  // 仪表半径 50 → 周长 314.16。按指数 / 100 填，不做拉伸。
  const fill = $('#g-fill');
  fill.style.strokeDashoffset = '314.16';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    fill.style.strokeDashoffset = String(314.16 * (1 - r['财富指数'] / 100));
  }));
  countUp($('#vc-index'), r['财富指数'], 1600);
  countUp($('#vc-beat'), r['胜过'], 1600);
}

function renderMeta(data, placeName) {
  const b = data.birth;
  const box = $('#birth-meta');
  box.innerHTML = '';
  const item = (label, value) => {
    const s = el('span', null, label + ' ');
    s.append(el('b', null, value));
    box.append(s);
  };
  item('八字', b['四柱'].join(' '));
  item('农历', b['农历']);
  item('真太阳时', b['真太阳时'].slice(11) + '（' + placeName + '）');

  const warn = $('#boundary');
  const gap = b['距时辰交界'];
  if (gap != null && gap <= 12) {
    warn.textContent = '提示：你的真太阳时距时辰交界仅 ' + gap +
      ' 分钟。若出生时间记录有出入，时柱可能不同，结果仅供参考。';
    warn.hidden = false;
  } else {
    warn.hidden = true;
  }
}

// ── 渲染：五力 ───────────────────────────────────────────
function renderForces(r) {
  const box = $('#forces');
  box.innerHTML = '';
  const fills = [];
  Object.keys(r['五力']).forEach((name) => {
    const f = r['五力'][name];
    const d = el('details', 'force' + (name === r['最强'] ? ' best' : ''));
    if (name === r['最弱']) d.open = true;   // 最弱一项默认展开：那正是最想追问的
    const sum = el('summary');
    const head = el('div', 'f-head');
    head.append(el('span', 'f-name', name), el('span', 'f-hint', f['释义']),
                el('span', 'f-band', f['评级']), el('span', 'f-score', String(f['分数'])));
    const track = el('div', 'f-track');
    const fill = el('div', 'f-fill');
    track.append(fill);
    sum.append(head, track);
    d.append(sum);

    const ul = el('ul', 'why');
    f['依据'].forEach((w, i) => {
      const advice = f['分数'] < 52 && i === f['依据'].length - 1;
      ul.append(el('li', advice ? 'advice' : null, w));
    });
    d.append(ul);
    box.append(d);
    fills.push([fill, f['分数']]);
  });
  // 条长严格按分数比例
  requestAnimationFrame(() => requestAnimationFrame(() => {
    fills.forEach(([n, s]) => { n.style.width = s + '%'; });
  }));
}

// ── 渲染：一生财运曲线 ───────────────────────────────────
/* 单序列折线：一条金线、2px；点 8px 带 2px 底色描边；只给峰值与「当下」
   直接标注，其余数值走悬停/点按提示与下方明细表。纵轴固定 40–100，
   不随数据缩放——缩放会把小起伏夸大成大起大落。 */
function renderCurve(steps) {
  const svg = $('#curve');
  svg.innerHTML = '';
  if (!steps.length) return;
  const W = 340, H = 190, L = 26, R = 14, T = 26, B = 34;
  const lo = 40, hi = 100;
  const x = (i) => L + (W - L - R) * (steps.length === 1 ? 0.5 : i / (steps.length - 1));
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));

  const defs = svgEl('defs', {});
  const grad = svgEl('linearGradient', { id: 'gArea', x1: 0, y1: 0, x2: 0, y2: 1 });
  grad.append(svgEl('stop', { offset: '0%', 'stop-color': '#D6B26A', 'stop-opacity': '.38' }));
  grad.append(svgEl('stop', { offset: '100%', 'stop-color': '#D6B26A', 'stop-opacity': '0' }));
  defs.append(grad);
  svg.append(defs);

  [50, 70, 90].forEach((v) => {
    svg.append(svgEl('line', { class: 'c-grid', x1: L, x2: W - R, y1: y(v), y2: y(v) }));
    const t = svgEl('text', { class: 'c-gridlabel', x: L - 6, y: y(v) + 3, 'text-anchor': 'end' });
    t.textContent = v;
    svg.append(t);
  });

  const pts = steps.map((s, i) => [x(i), y(s['指数'])]);
  // 平滑曲线（单调三次插值的简化版：控制点取相邻点水平中点，不会过冲）
  let d = 'M' + pts[0][0] + ',' + pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
    const cx = (x0 + x1) / 2;
    d += ' C' + cx + ',' + y0 + ' ' + cx + ',' + y1 + ' ' + x1 + ',' + y1;
  }
  const base = y(lo);
  svg.append(svgEl('path', { class: 'c-area',
    d: d + ' L' + pts[pts.length - 1][0] + ',' + base + ' L' + pts[0][0] + ',' + base + ' Z' }));
  svg.append(svgEl('path', { class: 'c-line', d: d }));

  const cross = svgEl('line', { class: 'c-cross', x1: 0, x2: 0, y1: T - 6, y2: base, visibility: 'hidden' });
  svg.append(cross);

  steps.forEach((s, i) => {
    const [px, py] = pts[i];
    const ax = svgEl('text', { class: 'c-axis', x: px, y: H - 16, 'text-anchor': 'middle' });
    ax.textContent = s['起始虚岁'] + '岁';
    svg.append(ax);
    const yr = svgEl('text', { class: 'c-gridlabel', x: px, y: H - 4, 'text-anchor': 'middle' });
    yr.textContent = s['年份'][0];
    svg.append(yr);

    svg.append(svgEl('circle', {
      class: 'c-dot' + (s['当下'] ? ' now' : '') + (s['高峰'] ? ' peak' : ''),
      cx: px, cy: py, r: s['高峰'] ? 5 : 4,
    }));
    if (s['高峰']) {
      const t = svgEl('text', { class: 'c-label', x: px, y: py - 11, 'text-anchor': 'middle' });
      t.textContent = '高峰 ' + s['指数'];
      svg.append(t);
    }
    if (s['当下'] && !s['高峰']) {
      const t = svgEl('text', { class: 'c-now', x: px, y: py - 10, 'text-anchor': 'middle' });
      t.textContent = '当下';
      svg.append(t);
    }
  });

  // 命中区：每个点一整列，比点本身大得多，手指好点
  const tip = $('#curve-tip');
  const colW = (W - L - R) / Math.max(1, steps.length - 1);
  const show = (i) => {
    const s = steps[i];
    const [px] = pts[i];
    cross.setAttribute('x1', px); cross.setAttribute('x2', px);
    cross.setAttribute('visibility', 'visible');
    tip.innerHTML = '';
    const head = el('div');
    head.append(el('b', null, s['大运'] + ' 运 · ' + s['指数']));
    tip.append(head,
      el('div', null, s['年份'][0] + '–' + s['年份'][1] + '（' + s['起始虚岁'] + ' 岁起）'),
      el('em', null, s['要点'].join(' · ')));
    tip.hidden = false;
    const box = svg.getBoundingClientRect();
    const scale = box.width / W;
    const left = Math.max(0, Math.min(box.width - 172, px * scale - 86));
    tip.style.left = left + 'px';
    // 提示框放在点的另一半，不压住线
    const py = pts[i][1];
    tip.style.top = (py < H / 2 ? Math.round(box.height * 0.5) : 0) + 'px';
  };
  const hide = () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); };
  steps.forEach((s, i) => {
    const hit = svgEl('rect', { class: 'c-hit', x: pts[i][0] - colW / 2, y: 0, width: colW, height: H });
    hit.addEventListener('pointerenter', () => show(i));
    hit.addEventListener('click', () => show(i));
    svg.append(hit);
  });
  svg.addEventListener('pointerleave', hide);

  // 明细表：同一份数据的文字版，也是读屏与色觉受限时的通道
  const rows = $('#curve-rows');
  rows.innerHTML = '';
  steps.forEach((s) => {
    const row = el('div', 'c-row' + (s['当下'] ? ' now' : ''));
    row.append(el('span', 'yr', s['年份'][0] + '–' + s['年份'][1]),
               el('span', 'gz', s['大运']),
               el('span', 'v', String(s['指数'])),
               el('span', 'notes', (s['高峰'] ? '★ 高峰 · ' : '') + (s['当下'] ? '当下 · ' : '') +
                                   s['要点'].join('、')));
    rows.append(row);
  });
}

// ── 渲染：近三年 ─────────────────────────────────────────
function renderYears(list) {
  const box = $('#years');
  box.innerHTML = '';
  list.forEach((y, i) => {
    const c = el('div', 'year' + (i === 0 ? ' this' : ''));
    if (i === 0) c.append(el('span', 'y-tag', '今年'));
    const head = el('div', 'y-head');
    head.append(el('span', 'y-year', String(y['年份'])),
                el('span', 'y-gz', y['干支'] + ' · ' + y['生肖'] + '年'));
    const stars = el('span', 'y-stars');
    stars.setAttribute('aria-label', y['星级'] + ' 星（满分 5 星）');
    for (let k = 1; k <= 5; k++) stars.append(el('span', k <= y['星级'] ? null : 'off', '★'));
    head.append(stars, el('span', 'y-verdict' + (y['星级'] <= 3 ? ' calm' : ''), y['定调']));
    c.append(head, el('p', 'y-theme', y['主题']));
    y['紫微'].forEach((n) => c.append(el('p', 'y-zw', n)));
    box.append(c);
  });
}

// ── 渲染：财从何来 ───────────────────────────────────────
function renderSource(r) {
  const bz = r['八字财星'], zw = r['紫微财帛'];

  const bt = $('#bz-tags');
  bt.innerHTML = '';
  ['日主 ' + bz['日主'], '财星 ' + bz['财星'], bz['格局'],
   '喜用 ' + bz['喜用'].join('')].forEach((t) => bt.append(el('span', null, t)));
  const bl = $('#bz-lines');
  bl.innerHTML = '';
  bz['要点'].forEach((t) => bl.append(el('li', null, t)));

  const zt = $('#zw-tags');
  zt.innerHTML = '';
  [zw['落宫'], zw['空宫'] ? '空宫借星' : '主星坐守'].concat(zw['格局'])
    .forEach((t) => zt.append(el('span', null, t)));

  const zs = $('#zw-stars');
  zs.innerHTML = '';
  zw['主星解'].forEach((s) => {
    const p = el('p', 'star-note');
    p.append(el('b', null, s['星']), document.createTextNode(s['解']));
    zs.append(p);
  });
  const zl = $('#zw-lines');
  zl.innerHTML = '';
  zl.append(el('li', 'dim', '会吉：' + zw['会吉星'].join('、')),
            el('li', 'dim', '会煞：' + zw['会煞星'].join('、')),
            el('li', 'dim', '四化：' + zw['四化'].join('、')));
}

function renderDual(r) {
  const box = $('#dual');
  box.innerHTML = '';
  [['八字', '五行生克'], ['紫微', '宫位星曜']].forEach(([k, sub]) => {
    const it = r['双盘'][k];
    const col = el('div', 'dual-col');
    col.append(el('h4', null, k + ' · ' + sub), el('span', 'n', String(it['分数'])));
    const d = el('details');
    d.append(el('summary', null, '看依据'));
    const ul = el('ul');
    it['依据'].forEach((w) => ul.append(el('li', null, w)));
    d.append(ul);
    col.append(d);
    box.append(col);
  });
}

// ── 渲染：招财指南 ───────────────────────────────────────
const COLOR_HEX = {
  '青': '#3E7D6E', '翠绿': '#2F8F5B', '朱红': '#C0392B', '紫': '#7B3F8C',
  '明黄': '#E2B33C', '驼色': '#B08A5A', '白': '#F2EEE6', '香槟金': '#D9C08A',
  '玄黑': '#1B1B1F', '深蓝': '#1F3A68',
};

function renderGuide(g) {
  const box = $('#guide');
  box.innerHTML = '';
  const tile = (title, cls) => {
    const t = el('div', 'g-tile' + (cls ? ' ' + cls : ''));
    t.append(el('h4', null, title));
    box.append(t);
    return t;
  };
  tile('旺财方位').append(el('div', 'v', g['旺财方位']));
  tile('贵人生肖').append(el('div', 'v', g['贵人生肖'].join(' · ')));

  const sw = el('div', 'swatches');
  g['幸运色'].forEach((c) => {
    const s = el('span', 'swatch');
    const dot = el('i');
    dot.style.background = COLOR_HEX[c] || '#D6B26A';
    s.append(dot, document.createTextNode(c));
    sw.append(s);
  });
  tile('幸运色').append(sw);

  const nums = el('div', 'nums');
  g['幸运数字'].forEach((n) => nums.append(el('b', null, String(n))));
  tile('幸运数字').append(nums);

  const tr = el('div', 'trades');
  g['宜从行业'].forEach((t) => tr.append(el('span', null, t)));
  tile('宜从行业', 'wide').append(tr);

  $('#guide-note').textContent = g['说明'];
}

// ── 复制给命理师的摘要 ───────────────────────────────────
function buildSummary(data, payload, placeName) {
  const r = data.report, b = data.birth;
  const forces = Object.keys(r['五力'])
    .map((k) => k.replace('力', '').replace('财', '') + r['五力'][k]['分数']).join(' ');
  return [
    '【子牙财鉴 · 财富测算】',
    (state.nick ? '称呼：' + state.nick + '\n' : '') +
    '公历：' + b['公历'] + '（' + placeName + '，' + b['性别'] + '）',
    '八字：' + b['四柱'].join(' '),
    '财富指数 ' + r['财富指数'] + '（' + r['品阶']['品阶'] + '·' + r['品阶']['名号'] +
      '，胜过 ' + r['胜过'] + '%）· ' + r['类型']['名称'],
    '五力：' + forces,
  ].join('\n');
}

// ── 主流程 ───────────────────────────────────────────────
function showResult(data, payload, placeName) {
  const r = data.report;
  state.summary = buildSummary(data, payload, placeName);

  $('#landing').hidden = true;
  $('#result').hidden = false;
  window.scrollTo(0, 0);

  renderCard(data, payload);
  renderMeta(data, placeName);
  $('#tier-desc').textContent = r['品阶']['品阶'] + ' · ' + r['品阶']['名号'] + '　' + r['类型']['释义'];
  $('#summary').textContent = r['总评'];
  renderForces(r);
  renderCurve(r['一生财运']);
  renderYears(r['近年']);
  renderSource(r);
  renderDual(r);
  renderGuide(r['招财']);
}

async function loadPrice() {
  try {
    const cfg = await (await fetch('/api/config')).json();
    if (cfg.premium_price) {
      const p = $('#pm-price');
      p.textContent = cfg.premium_price;
      p.append(el('small', null, '/ 份 · 真人一对一'));
      p.hidden = false;
    }
    if (cfg.shop_note) {
      $('#shop-note').textContent = cfg.shop_note;
      const btn = $('#shop-name');
      if (cfg.shop_name) {
        btn.textContent = cfg.shop_name + '　复制';
        btn.addEventListener('click', async () => {
          const ok = await copyText(cfg.shop_name);
          showToast(ok ? '店铺名已复制，去平台里搜索即可' : '请手动搜索：' + cfg.shop_name);
        });
      } else {
        btn.hidden = true;
      }
      $('#shop').hidden = false;
    }
    if (cfg.shop_name) {
      const v = $('#vc-shop');
      v.textContent = '测你的财富指数 · 各平台搜「' + cfg.shop_name + '」';
      v.hidden = false;
    }
  } catch (_) { /* 价格与店铺名不是必需项，拿不到就不显示 */ }
}

document.addEventListener('DOMContentLoaded', () => {
  initDust();
  const dateInput = initBirthDate();
  dateInput.set(1990, 1, 1);
  $('#by').value = '';
  ZiyaPlaces.initPicker();
  const ask = initWechat(state);
  loadPrice();

  $('#go-form').addEventListener('click', () => scrollToEl($('#intake'), 12));

  $('#unlock').addEventListener('click', () => ask('我想要一份完整的财富精批'));

  $('#birth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = $('#form-error');
    err.hidden = true;
    const form = readForm(dateInput);
    if (form.error) {
      err.textContent = form.error;
      err.hidden = false;
      return;
    }
    state.nick = ($('#nick').value || '').trim().slice(0, 8);
    try {
      const data = await cast(form.payload);
      showResult(data, form.payload, form.place);
    } catch (ex) {
      err.textContent = ex.message || '网络异常，请稍后再试';
      err.hidden = false;
    }
  });

  $('#redo').addEventListener('click', () => {
    $('#result').hidden = true;
    $('#landing').hidden = false;
    $('#nick').value = '';
    scrollToEl($('#intake'), 12);
  });
});
