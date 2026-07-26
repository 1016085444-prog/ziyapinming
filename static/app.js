/* 子牙品命 — 前端。无构建步骤，原生 ES module 语法即可。 */

'use strict';

// 出生地经度决定真太阳时校正量。乌鲁木齐用北京时间时偏差近两小时，
// 足以整体错一到两个时辰——所以这个选择不是装饰。
const CITIES = [
  ['北京', 116.41, 39.90], ['上海', 121.47, 31.23], ['广州', 113.26, 23.13],
  ['深圳', 114.06, 22.55], ['成都', 104.07, 30.57], ['杭州', 120.15, 30.27],
  ['武汉', 114.30, 30.59], ['西安', 108.94, 34.34], ['重庆', 106.55, 29.56],
  ['南京', 118.80, 32.06], ['天津', 117.20, 39.13], ['苏州', 120.58, 31.30],
  ['长沙', 112.94, 28.23], ['郑州', 113.62, 34.75], ['青岛', 120.38, 36.07],
  ['沈阳', 123.43, 41.80], ['大连', 121.62, 38.91], ['昆明', 102.83, 24.88],
  ['哈尔滨', 126.53, 45.80], ['济南', 117.00, 36.65], ['福州', 119.30, 26.08],
  ['厦门', 118.09, 24.48], ['合肥', 117.28, 31.86], ['南昌', 115.89, 28.68],
  ['石家庄', 114.51, 38.04], ['太原', 112.55, 37.87], ['长春', 125.32, 43.82],
  ['南宁', 108.37, 22.82], ['贵阳', 106.63, 26.65], ['兰州', 103.82, 36.06],
  ['乌鲁木齐', 87.62, 43.83], ['拉萨', 91.11, 29.65], ['呼和浩特', 111.75, 40.84],
  ['银川', 106.23, 38.49], ['西宁', 101.78, 36.62], ['海口', 110.20, 20.04],
  ['香港', 114.17, 22.32], ['澳门', 113.55, 22.20], ['台北', 121.52, 25.03],
];

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

// summary 保存「八字 + 出生信息」，用于拼接复制给命理师的消息
let state = { wechatId: '', summary: '' };

// 推演停顿的毫秒数。见提交处理里的说明；设为 0 即恢复秒出。
const CAST_BEAT = 850;

// ── 初始化 ───────────────────────────────────────────────

(function initCities() {
  const sel = $('#city-select');
  CITIES.forEach(([name], i) => sel.add(new Option(name, String(i))));
  sel.add(new Option('其他 / 海外（用高级选项填经度）', 'custom'));
})();

/* 星场。用固定种子而不是 Math.random：刷新页面星星不该换位置，
   否则每次进站都像换了张背景图，反而显得廉价。 */
(function initStarfield() {
  const svg = $('#starfield');
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
})();

(async function loadConfig() {
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
})();

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

// ── 排盘 ─────────────────────────────────────────────────

$('#birth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const errBox = $('#form-error');
  errBox.hidden = true;

  const date = form.date.value;
  const time = form.time.value;
  if (!date || !time) {
    errBox.textContent = '请填写出生日期与时刻';
    errBox.hidden = false;
    return;
  }

  const [y, mo, d] = date.split('-').map(Number);
  const [h, mi] = time.split(':').map(Number);

  const cityVal = form.city.value;
  let lon = 116.41, lat = 39.90, cityName = '';
  if (cityVal !== 'custom') {
    const c = CITIES[Number(cityVal)];
    lon = c[1]; lat = c[2]; cityName = c[0];
  }
  if (form.longitude.value !== '') lon = Number(form.longitude.value);

  const btn = form.querySelector('button[type=submit]');
  btn.disabled = true;
  btn.classList.add('casting');
  btn.textContent = '推 演 中';
  const startedAt = Date.now();

  try {
    const res = await fetch('/api/chart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        year: y, month: mo, day: d, hour: h, minute: mi,
        gender: form.gender.value,
        longitude: lon, latitude: lat,
        use_true_solar_time: form.tst.checked,
        late_zi_shifts_day: form.latezi.checked,
      }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || '排盘失败');

    const data = await res.json();

    // 排盘是本地计算，几毫秒就返回。这里刻意留一个推演的停顿——
    // 秒出结果会让人觉得只是查了张表，反而折损可信度。
    // 嫌慢就把 CAST_BEAT 调成 0。
    const wait = CAST_BEAT - (Date.now() - startedAt);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));

    render(data, cityName);
    $('#landing').hidden = true;
    $('#result').hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (err) {
    errBox.textContent = err.message;
    errBox.hidden = false;
  } finally {
    btn.disabled = false;
    btn.classList.remove('casting');
    btn.textContent = '排 盘';
  }
});

$('#redo').addEventListener('click', () => {
  $('#result').hidden = true;
  $('#landing').hidden = false;
  window.scrollTo({ top: 0 });
});

$('#go-form').addEventListener('click', () => {
  scrollToEl($('#intake'), 16);
});

// ── 渲染 ─────────────────────────────────────────────────

function render(data, cityName) {
  const chart = data.chart;
  const bazi = chart['四柱'].map((p) => p['干支']).join(' ');
  const b = chart['出生'];
  state.summary =
    '八字：' + bazi + '\n' +
    '（' + b['性别'] + '，' + b['标准时'] +
    (cityName ? ' 生于' + cityName : '') + '）';

  renderMeta(chart);
  renderPillars(chart);
  renderElements(data.analysis);
  renderLuck(chart, data.years);
  renderShensha(chart);
}

function renderMeta(chart) {
  const b = chart['出生'];
  const box = $('#birth-meta');
  box.innerHTML = '';
  const line = (label, value) => {
    const p = el('div');
    p.append(label + '：');
    p.append(el('b', null, value));
    return p;
  };
  box.append(line('公历', b['标准时'] + '（' + b['性别'] + '）'));
  box.append(line('真太阳时', b['真太阳时']));
  box.append(line('生肖', b['生肖'] + ' · ' + chart['胎元'] + '（胎元）· ' +
                          chart['空亡'] + '（空亡）'));
  box.append(line('节气', chart['节气']['上一节'] + ' → ' + chart['节气']['下一节']));
}

function renderPillars(chart) {
  const table = $('#pillars');
  table.innerHTML = '';
  const cols = chart['四柱'];

  const thead = el('thead');
  const hr = el('tr');
  hr.append(el('th', 'row-label', ''));
  ['年柱', '月柱', '日柱', '时柱'].forEach((n) => hr.append(el('th', null, n)));
  thead.append(hr);
  table.append(thead);

  const tbody = el('tbody');
  const addRow = (label, cellFn) => {
    const tr = el('tr');
    tr.append(el('td', 'row-label', label));
    cols.forEach((c) => tr.append(cellFn(c)));
    tbody.append(tr);
  };

  addRow('十神', (c) => {
    const td = el('td', 'god', c['天干十神']);
    if (c['天干十神'] === '日主') td.classList.add('day-master');
    return td;
  });
  addRow('天干', (c) => {
    const td = el('td');
    td.append(el('span', 'gz e-' + c['天干五行'], c['天干']));
    return td;
  });
  addRow('地支', (c) => {
    const td = el('td');
    td.append(el('span', 'gz e-' + c['地支五行'], c['地支']));
    return td;
  });
  addRow('藏干', (c) => {
    const td = el('td', 'hidden-stems');
    c['藏干'].forEach((h) => {
      const row = el('div');
      row.append(el('span', null, h['干']));
      row.append(el('span', 'hs-god', ' ' + h['十神']));
      td.append(row);
    });
    return td;
  });
  addRow('十二运', (c) => el('td', 'small', c['十二运']));
  addRow('纳音', (c) => el('td', 'small', c['纳音']));

  table.append(tbody);
}

/* 五行生克图：五行本就是一个五边形——外环相生（木→火→土→金→水→木），
   内星相克（木克土、火克金、土克水、金克木、水克火）。用五角图既比条形图
   好看，也多传递了「生克关系」这层条形图根本表达不了的信息。
   节点半径随该五行力量变化，一眼能看出哪一行独大、哪一行几近于无。 */
const WUXING = [
  { name: '木', angle: -90 },
  { name: '火', angle: -18 },
  { name: '土', angle: 54 },
  { name: '金', angle: 126 },
  { name: '水', angle: 198 },
];
const R_ORBIT = 32;   // 节点所在圆的半径（viewBox 圆心 50,50）

const svgEl = (tag, attrs) => {
  const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
};

function renderWuxing(analysis) {
  const svg = $('#wuxing');
  svg.innerHTML = '';
  const pct = analysis['五行占比'];

  const pts = WUXING.map((w) => {
    const rad = (w.angle * Math.PI) / 180;
    return {
      ...w,
      x: 50 + R_ORBIT * Math.cos(rad),
      y: 50 + R_ORBIT * Math.sin(rad),
      value: parseFloat(pct[w.name]),
      rad,
    };
  });

  // 相克（内星）先画，压在相生环下面
  pts.forEach((p, i) => {
    const target = pts[(i + 2) % 5];
    svg.append(svgEl('line', {
      class: 'wuxing-ke',
      x1: p.x, y1: p.y, x2: target.x, y2: target.y,
    }));
  });

  // 相生（外环）
  svg.append(svgEl('polygon', {
    class: 'wuxing-edge',
    points: pts.map((p) => p.x.toFixed(2) + ',' + p.y.toFixed(2)).join(' '),
  }));

  pts.forEach((p) => {
    // 单一五行占比很少超过 45%，按此归一化。
    // 半径设了下限：圆必须始终容得下五行字，否则 0% 那个节点会缩得比字还小。
    // 强弱靠「大小 + 填充深浅」双重编码，比单靠大小更易分辨。
    const t = Math.min(p.value, 45) / 45;
    const r = 8.5 + t * 5.5;

    const g = svgEl('g', { class: 'e-' + p.name });
    g.append(svgEl('circle', {
      class: 'wuxing-node', cx: p.x, cy: p.y, r: r,
      fill: 'currentColor', 'fill-opacity': (0.07 + t * 0.30).toFixed(3),
      stroke: 'currentColor', 'stroke-width': .6,
      'stroke-opacity': (0.35 + t * 0.5).toFixed(3),
    }));
    const glyph = svgEl('text', {
      class: 'wuxing-glyph', x: p.x, y: p.y, fill: 'currentColor',
    });
    glyph.textContent = p.name;
    g.append(glyph);
    svg.append(g);

    // 百分比推到节点外侧，避免压住连线
    const lr = R_ORBIT + r + 6;
    const pctLabel = svgEl('text', {
      class: 'wuxing-pct',
      x: 50 + lr * Math.cos(p.rad),
      y: 50 + lr * Math.sin(p.rad),
    });
    pctLabel.textContent = pct[p.name];
    svg.append(pctLabel);
  });
}

function renderElements(analysis) {
  renderWuxing(analysis);

  const s = analysis['日主旺衰'];
  const f = analysis['喜忌'];
  const v = $('#verdict');
  v.innerHTML = '';
  const dl = el('dl');
  const pair = (k, val) => {
    dl.append(el('dt', null, k));
    dl.append(el('dd', null, val));
  };
  pair('日主', s['日主五行'] + ' · ' + s['结论'] + '（扶抑比 ' + s['扶抑比'] + '）');
  pair('格局', analysis['格局']['格局'] + ' — ' + analysis['格局']['依据']);
  pair('喜用', f['喜用'].join('、') + '　　忌神：' + f['忌神'].join('、'));
  pair('取用依据', f['取用依据'] + (f['调候'] ? ' ' + f['调候'] : ''));
  v.append(dl);
}

function renderLuck(chart, years) {
  const luck = chart['大运'];
  $('#luck-start').textContent = luck['排法'] + '　' + luck['起运'];

  const strip = $('#luck-strip');
  strip.innerHTML = '';
  const current = years && years[0] ? years[0]['所行大运'] : null;

  luck['各步'].forEach((lp) => {
    const cell = el('div', 'luck-cell');
    if (lp['干支'] === current) cell.classList.add('current');
    cell.append(el('div', 'lg', lp['干支']));
    cell.append(el('div', 'lt', lp['天干十神']));
    cell.append(el('div', 'ly', lp['年份区间']));
    strip.append(cell);
  });

  const cur = strip.querySelector('.current');
  if (cur) cur.scrollIntoView({ block: 'nearest', inline: 'center' });
}

function renderShensha(chart) {
  const box = $('#shensha');
  box.innerHTML = '';
  const GOOD = ['天乙贵人', '文昌贵人', '将星', '华盖'];

  const shensha = chart['神煞'];
  if (shensha && Object.keys(shensha).length) {
    const g = el('div', 'tag-group');
    g.append(el('span', 'tg-label', '神煞'));
    Object.keys(shensha).forEach((k) => {
      const val = shensha[k];
      const tag = el('span', 'tag',
        Array.isArray(val) ? k + ' ' + val.join('') : k);
      tag.classList.add(GOOD.indexOf(k) >= 0 ? 'good' : 'warn');
      g.append(tag);
    });
    box.append(g);
  }

  const rel = chart['刑冲合害'];
  Object.keys(rel).forEach((kind) => {
    const g = el('div', 'tag-group');
    g.append(el('span', 'tg-label', kind));
    rel[kind].forEach((item) => {
      const tag = el('span', 'tag', item);
      tag.classList.add(
        (kind === '六合' || kind === '三合' || kind === '三会') ? 'good' : 'warn');
      g.append(tag);
    });
    box.append(g);
  });

  $('#shensha-panel').hidden = !box.children.length;
}

// ── 引流 ─────────────────────────────────────────────────

/* 点问题标签 = 把「八字 + 问题」整段复制好。
   用户加上微信直接粘贴就能发出第一条消息，省掉「我该说什么」这一步，
   这一步的摩擦正是私域引流最常见的流失点。 */
$('#suggestions').addEventListener('click', async (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;

  const msg = state.summary + '\n想问：' + chip.textContent;
  const ok = await copyText(msg);
  showToast(ok ? '八字和问题已复制，加微信后直接粘贴发我'
                : '复制失败，请截图本页发我');
  // 无论复制成不成功都滚过去：点标签的意图就是「我想问这个」，
  // 复制失败时更需要把联系方式送到眼前，否则用户看着提示却找不到人。
  scrollToEl($('.wechat-card'), 90);
});

$('#copy-wx').addEventListener('click', async () => {
  const ok = await copyText(state.wechatId);
  showToast(ok ? '微信号已复制' : '复制失败：' + state.wechatId);
});
