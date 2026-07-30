/* 子牙品命 — 八字页前端。无构建步骤，原生 ES module 语法即可。

   共用的东西不在这里：
     common.js  剪贴板、提示条、星场、微信卡、雷达图
     places.js  出生地选择器与城市表、生辰在两页之间的 URL 往返 */

'use strict';

// summary 保存「八字 + 出生信息」，用于拼接复制给命理师的消息
let state = { wechatId: '', summary: '' };

// 推演停顿的毫秒数。见提交处理里的说明；设为 0 即恢复秒出。
const CAST_BEAT = 850;

// ── 初始化 ───────────────────────────────────────────────

initStarfield('#starfield');
ZiyaPlaces.initPicker();
const selectedPlace = ZiyaPlaces.selected;
// 返回的 askQuestion 供「待定论」里的按钮取用
const askQuestion = initWechat(state);

// ── 排盘 ─────────────────────────────────────────────────

$('#birth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const p = readForm(e.target);
  if (p) await cast(p, true);
});

/* 读表单，拼成请求参数。缺日期或时刻则报错并返回 null。

   刻意与 cast 分开：从 URL 带参进来时，参数**直接**交给 cast，不经过
   「写进表单再读回来」这一圈。浏览器会在同地址重新加载时恢复上一次的
   表单值，而那次恢复的时机与页尾脚本是竞态的——紫微页曾因此出现过
   URL 写着 1990 年、盘却按 2000 年排的情况。DOM 不该当作参数的传递通道。 */
function readForm(form) {
  const errBox = $('#form-error');
  errBox.hidden = true;

  const date = form.date.value;
  const time = form.time.value;
  if (!date || !time) {
    errBox.textContent = '请填写出生日期与时刻';
    errBox.hidden = false;
    return null;
  }

  const [y, mo, d] = date.split('-').map(Number);
  const [h, mi] = time.split(':').map(Number);
  return {
    year: y, month: mo, day: d, hour: h, minute: mi,
    gender: form.gender.value,
    tst: form.tst.checked, latezi: form.latezi.checked, dst: form.dst.checked,
  };
}

/** 排盘并渲染。beat 为 false 时跳过推演停顿（从 URL 带参进来时用）。 */
async function cast(p, beat) {
  const errBox = $('#form-error');
  const place = selectedPlace();
  const btn = $('#birth-form').querySelector('button[type=submit]');
  btn.disabled = true;
  btn.classList.add('casting');
  btn.textContent = '推 演 中';
  const startedAt = Date.now();

  try {
    const res = await fetch('/api/chart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        year: p.year, month: p.month, day: p.day,
        hour: p.hour, minute: p.minute,
        gender: p.gender,
        longitude: place.longitude,
        tz_offset: place.tz,
        use_true_solar_time: p.tst,
        late_zi_shifts_day: p.latezi,
        adjust_china_dst: p.dst,
      }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || '排盘失败');

    const data = await res.json();

    // 排盘是本地计算，几毫秒就返回。这里刻意留一个推演的停顿——
    // 秒出结果会让人觉得只是查了张表，反而折损可信度。
    // 嫌慢就把 CAST_BEAT 调成 0。
    if (beat) {
      const wait = CAST_BEAT - (Date.now() - startedAt);
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    }

    render(data, place.name);
    // 把这个生辰挂到「换紫微斗数」的链接上，免得用户重填一遍
    $('#to-ziwei').href = '/ziwei' + ZiyaPlaces.birthQuery({
      year: p.year, month: p.month, day: p.day,
      hour: p.hour, minute: p.minute,
      gender: p.gender, place: place.name,
      tst: p.tst, latezi: p.latezi, dst: p.dst,
    });
    $('#landing').hidden = true;
    $('#result').hidden = false;
    window.scrollTo({ top: 0, behavior: beat ? 'smooth' : 'auto' });
  } catch (err) {
    errBox.textContent = err.message;
    errBox.hidden = false;
  } finally {
    btn.disabled = false;
    btn.classList.remove('casting');
    btn.textContent = '排 盘';
  }
}

/* 从紫微页带着生辰跳过来时，直接出盘，不必重填一遍。 */
(function autoCastFromQuery() {
  const b = ZiyaPlaces.readBirthQuery();
  if (!b) return;

  // 先排盘（用 URL 里的参数，不经表单），再填表单供「重新排盘」时核对
  cast(b, false);

  const form = $('#birth-form');
  const pad = (n) => String(n).padStart(2, '0');
  form.date.value = b.year + '-' + pad(b.month) + '-' + pad(b.day);
  form.time.value = pad(b.hour) + ':' + pad(b.minute);
  form.gender.value = b.gender;
  form.tst.checked = b.tst;
  form.latezi.checked = b.latezi;
  form.dst.checked = b.dst;
})();

$('#redo').addEventListener('click', () => {
  $('#result').hidden = true;
  $('#landing').hidden = false;
  window.scrollTo({ top: 0 });
});

$('#go-form').addEventListener('click', () => {
  scrollToEl($('#intake'), 16);
});

// ── 渲染 ─────────────────────────────────────────────────

function render(data, placeName) {
  const chart = data.chart;
  const bazi = chart['四柱'].map((p) => p['干支']).join(' ');
  const b = chart['出生'];
  state.summary =
    '八字：' + bazi + '\n' +
    '（' + b['性别'] + '，' + (b['登记时刻'] || b['标准时']) +
    (placeName ? ' 生于' + placeName : '') + '）';

  renderMeta(chart);
  renderPillars(chart);
  renderScores(data.scores);
  renderElements(data.analysis);
  renderLuck(chart, data.years);
  renderYears(data.years);
  renderShensha(chart);
  renderInquiry(data.inquiry);
}

/* 流年。今年单独放大，后两年压成小卡——注意力该给当下，
   但把后两年摆出来能让人意识到「这是有时间性的东西」。 */
function renderYears(years) {
  const box = $('#years');
  if (!box) return;
  box.innerHTML = '';
  if (!years || !years.length) return;

  const cur = years[0];
  const head = el('div', 'year-now');

  const top = el('div', 'yn-top');
  top.append(el('span', 'yn-year', cur['年份'] + ' 年'));
  top.append(el('span', 'yn-gz', cur['流年干支']));
  top.append(el('span', 'yn-god', cur['流年天干十神']));
  head.append(top);

  if (cur['流年主题']) head.append(el('p', 'yn-theme', cur['流年主题']));

  const tone = cur['五行取向'];
  const tag = el('span', 'yn-tone', tone);
  if (tone.indexOf('契合') >= 0) tag.classList.add('good');
  else if (tone.indexOf('忌') >= 0) tag.classList.add('warn');
  const meta = el('div', 'yn-meta');
  meta.append(tag);
  meta.append(el('span', null, '所行大运 ' + cur['所行大运']));
  meta.append(el('span', null, '虚岁 ' + cur['虚岁']));
  head.append(meta);

  // 刑冲合会是「今年被触动了什么」，用户最在意这块
  const stirred = [];
  ['大运引动', '流年引动'].forEach(function (k) {
    const g = cur[k];
    if (!g) return;
    Object.keys(g).forEach(function (kind) {
      if (kind === '说明') return;
      g[kind].forEach(function (item) { stirred.push(item); });
    });
  });
  if (stirred.length) {
    const s = el('div', 'yn-stir');
    s.append(el('span', 'yn-stir-label', '今年被引动'));
    stirred.forEach(function (t) { s.append(el('span', 'tag warn', t)); });
    head.append(s);
  }
  box.append(head);

  const rest = el('div', 'year-rest');
  years.slice(1).forEach(function (y) {
    const c = el('div', 'year-mini');
    c.append(el('div', 'ym-year', y['年份'] + ''));
    c.append(el('div', 'ym-gz', y['流年干支']));
    c.append(el('div', 'ym-god', y['流年天干十神']));
    rest.append(c);
  });
  if (rest.children.length) box.append(rest);
}

/* 待定论。整条漏斗里唯一让用户想到「我的情况比较特殊」的地方。
   点任意一条 = 把八字和这个问题一起复制好，直接就能发给命理师。 */
function renderInquiry(items) {
  const panel = $('#inquiry-panel');
  const box = $('#inquiry-list');
  if (!panel || !box) return;
  box.innerHTML = '';
  if (!items || !items.length) { panel.hidden = true; return; }
  panel.hidden = false;

  items.forEach(function (q) {
    const card = el('div', 'inq');
    card.append(el('div', 'inq-title', q['标题']));
    card.append(el('p', 'inq-fact', q['事实']));
    card.append(el('p', 'inq-fork', q['两可']));

    const ask = el('button', 'inq-ask');
    ask.type = 'button';
    ask.append(el('span', 'inq-q', q['问题']));
    ask.append(el('span', 'inq-go', '带着这个问题问 →'));
    ask.addEventListener('click', function () { askQuestion(q['问法'] || q['问题']); });
    card.append(ask);
    box.append(card);
  });
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
  // 「公历」必须显示用户自己填的时刻。曾经这里显示的是夏令时回退后的
  // 标准时——用户填 10:30 看到 09:30，会以为程序算错了。
  // 两步校正分行列出，用户能一眼核对推导链，而不是面对一个凭空的数字。
  box.append(line('公历', (b['登记时刻'] || b['标准时'])
                          + '（' + b['性别'] + '）'));
  if (b['已回退夏令时']) {
    box.append(line('夏令时', '已回退 1 小时 → 标准时 ' + b['标准时']));
  }
  box.append(line('真太阳时', b['真太阳时']));

  // 时辰交界提醒：越靠近交界，时柱越经不起出生时间与经度的微小误差。
  // 与其让用户以为结果绝对可靠，不如把不确定性讲明白。
  const gap = b['距时辰交界'];
  if (gap <= 12) {
    const warn = el('div', 'meta-warn');
    warn.textContent =
      '⚠ 真太阳时距时辰交界仅 ' + gap + ' 分钟。出生时间若有几分钟出入，'
      + '时柱就会变——建议向家人核实准确到分钟的出生时刻。';
    box.append(warn);
  }
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
