/* 子牙品命 — 紫微页前端。无构建步骤。

   共用的东西不在这里：
     common.js  剪贴板、提示条、星场、微信卡、雷达图
     places.js  出生地选择器与城市表、生辰在两页之间的 URL 往返 */

'use strict';

// summary 保存「命盘摘要 + 出生信息」，用于拼接复制给命理师的消息
let state = { wechatId: '', summary: '' };

// 推演停顿的毫秒数。与八字页同一个理由：秒出结果会让人觉得只是查了张表。
const CAST_BEAT = 850;

/* 十二宫在四四方阵里的位置。这不是任意的排版选择——紫微盘自古就是
   这个形制：地支自左下角的寅起，沿逆时针方向绕行一周。

   写成 [行, 列]（都从 1 起）：

       巳 午 未 申
       辰 ▢▢▢▢ 酉
       卯 ▢▢▢▢ 戌
       寅 丑 子 亥          */
const CELL_POS = [
  [4, 3],  // 子
  [4, 2],  // 丑
  [4, 1],  // 寅
  [3, 1],  // 卯
  [2, 1],  // 辰
  [1, 1],  // 巳
  [1, 2],  // 午
  [1, 3],  // 未
  [1, 4],  // 申
  [2, 4],  // 酉
  [3, 4],  // 戌
  [4, 4],  // 亥
];

// 格子里显示到杂曜为止会挤爆，所以只放这几颗——它们是论断真正用得上的。
// 其余杂曜全在宫位详情里，一颗不少。
const CELL_MINOR = ['禄存', '天马'];

// 排盘结果留在内存里，供点开宫位详情时取用
let chartData = null;

// ── 初始化 ───────────────────────────────────────────────

initStarfield('#starfield');
ZiyaPlaces.initPicker();
const birthDate = initBirthDate();
const askQuestion = initWechat(state);

$('#go-form').addEventListener('click', () => scrollToEl($('#intake'), 16));

$('#redo').addEventListener('click', () => {
  $('#result').hidden = true;
  $('#landing').hidden = false;
  window.scrollTo({ top: 0 });
});

// ── 排盘 ─────────────────────────────────────────────────

$('#birth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const p = readForm(e.target);
  if (p) await cast(p, true);
});

/* 读表单，拼成请求参数。缺日期或时刻则报错并返回 null。

   刻意与 cast 分开：从 URL 带参进来时，参数**直接**交给 cast，不经过
   「写进表单再读回来」这一圈。浏览器会在同地址重新加载时恢复上一次的
   表单值，而那次恢复的时机与页尾脚本是竞态的——曾经因此出现过 URL 写着
   1990 年、盘却按 2000 年排的情况。DOM 不该当作参数的传递通道。 */
function readForm(form) {
  const errBox = $('#form-error');
  errBox.hidden = true;

  const ymd = birthDate.read();
  const time = form.time.value;
  if (!ymd) {
    errBox.textContent = '请填写出生年份（1900–2100 之间）';
    errBox.hidden = false;
    return null;
  }
  if (!time) {
    errBox.textContent = '请填写出生时刻';
    errBox.hidden = false;
    return null;
  }

  const [h, mi] = time.split(':').map(Number);
  return {
    year: ymd.year, month: ymd.month, day: ymd.day, hour: h, minute: mi,
    gender: form.gender.value,
    tst: form.tst.checked, latezi: form.latezi.checked, dst: form.dst.checked,
    yb: form.yb.value, lm: form.lm.value,
  };
}

/** 排盘并渲染。beat 为 false 时跳过推演停顿（从 URL 带参进来时用）。 */
async function cast(p, beat) {
  const errBox = $('#form-error');
  const place = ZiyaPlaces.selected();
  const btn = $('#birth-form').querySelector('button[type=submit]');
  btn.disabled = true;
  btn.classList.add('casting');
  btn.textContent = '推 演 中';
  const startedAt = Date.now();

  try {
    const res = await fetch('/api/ziwei', {
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
        year_boundary: p.yb || 'lunar',
        leap_month_rule: p.lm || 'current',
      }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || '排盘失败');

    const data = await res.json();

    if (beat) {
      const wait = CAST_BEAT - (Date.now() - startedAt);
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    }

    render(data, place.name);
    // 把这个生辰挂到所有「换八字」的入口上，免得用户重填一遍。
    // 用类而不是 id：命盘旁与「为什么分数不同」里各有一个入口。
    const q = '/' + ZiyaPlaces.birthQuery({
      year: p.year, month: p.month, day: p.day,
      hour: p.hour, minute: p.minute,
      gender: p.gender, place: place.name,
      tst: p.tst, latezi: p.latezi, dst: p.dst,
    });
    document.querySelectorAll('.to-other').forEach((a) => { a.href = q; });
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

/* 从八字页带着生辰跳过来时，直接出盘，不必重填一遍。
   跳过推演停顿——那个停顿是给「刚提交」的人看的，这里人已经等过一次了。 */
(function autoCastFromQuery() {
  const b = ZiyaPlaces.readBirthQuery();
  if (!b) return;

  // 先排盘（用 URL 里的参数，不经表单），再把表单填上供「重新排盘」时核对。
  // 顺序反过来就会被浏览器的表单恢复覆盖掉。
  cast(b, false);

  const form = $('#birth-form');
  const pad = (n) => String(n).padStart(2, '0');
  birthDate.set(b.year, b.month, b.day);
  form.time.value = pad(b.hour) + ':' + pad(b.minute);
  form.gender.value = b.gender;
  form.tst.checked = b.tst;
  form.latezi.checked = b.latezi;
  form.dst.checked = b.dst;
})();

// ── 渲染 ─────────────────────────────────────────────────

function render(data, placeName) {
  chartData = data;
  const c = data.chart;
  const b = c['出生'];
  const p = c['命盘'];

  // 复制给命理师的摘要。紫微的要目是「命宫坐什么 + 五行局」，
  // 而不是八个字——所以这段和八字页刻意不同。
  const lifeStars = mainStarsOf(c, p['命宫']);
  state.summary =
    '紫微盘：命宫在' + p['命宫'] + '（' + (lifeStars || '空宫') + '）· ' +
    p['五行局'] + '\n' +
    '农历：' + b['农历'] + ' ' + b['时辰'] + '\n' +
    '（' + b['性别'] + '，' + (b['登记时刻'] || b['标准时']) +
    (placeName ? ' 生于' + placeName : '') + '）';

  renderMeta(c);
  renderGrid(data);
  renderScores(data.scores);           // common.js，六轴自适应
  renderSihua(data.analysis);
  renderPatterns(data.analysis);
  renderLimits(c, data.years);
  renderYears(data.years);
  renderInquiry(data.inquiry);
}

/** 某地支所在宫的主星名（含借星），用于摘要。 */
function mainStarsOf(chart, branch) {
  const pal = chart['十二宫'].find((x) => x['地支'] === branch);
  if (!pal) return '';
  const own = pal['星曜'].filter((s) => s['类'] === '主星');
  if (own.length) return own.map((s) => s['名'] + (s['亮度'] || '')).join('');
  const bor = pal['借星'].map((s) => s['名']).join('');
  return bor ? '借' + bor : '';
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

  // 「公历」显示用户自己填的时刻。八字页曾在这里踩过坑：显示夏令时回退后的
  // 标准时，用户填 10:30 看到 09:30，会以为程序算错了。
  box.append(line('公历', (b['登记时刻'] || b['标准时']) + '（' + b['性别'] + '）'));
  if (b['已回退夏令时']) {
    box.append(line('夏令时', '已回退 1 小时 → 标准时 ' + b['标准时']));
  }
  box.append(line('真太阳时', b['真太阳时'] + '　' + b['时辰']));
  box.append(line('农历', b['农历'] + '　' + b['生肖'] + '年　' + b['阴阳']));
  if (b['闰月处理']) box.append(line('闰月', b['闰月处理']));
}

/* 十二宫盘。 */
function renderGrid(data) {
  const c = data.chart;
  const grid = $('#zw-grid');
  grid.innerHTML = '';

  const lifeBranch = c['命盘']['命宫'];
  // 当前所行大限，用来在盘上高亮那一宫——用户第一个想知道的就是「我现在走哪」
  const currentLimit = data.years && data.years[0]
    ? data.years[0]['所行大限'] : '';

  c['十二宫'].forEach((pal, i) => {
    const [row, col] = CELL_POS[i];
    const cell = el('button', 'zw-cell');
    cell.type = 'button';
    cell.style.gridRow = String(row);
    cell.style.gridColumn = String(col);

    if (pal['地支'] === lifeBranch) cell.classList.add('is-life');
    if (currentLimit && currentLimit.indexOf(pal['宫名']) === 0) {
      cell.classList.add('is-limit');
    }
    if (pal['身宫']) {
      const tag = el('i', 'zw-body-tag', '身');
      tag.setAttribute('aria-label', '身宫');
      cell.append(tag);
    }

    // ── 星曜 ──
    const stars = el('div', 'zw-stars');
    const shown = pal['星曜'].filter(
      (s) => s['类'] !== '杂曜' || CELL_MINOR.indexOf(s['名']) >= 0);

    shown.forEach((s) => stars.append(starChip(s)));
    cell.append(stars);

    // 空宫把借来的主星补上，否则整格看着像漏了东西。
    // 另起一行而不是接在本宫星曜后面——挨着排会让人以为借来的星是本宫的。
    if (pal['空宫'] && pal['借星'].length) {
      const box = el('div', 'zw-stars zw-borrowed');
      pal['借星'].forEach((s) => {
        const n = starChip(s);
        n.classList.add('borrowed');
        n.firstChild.textContent = '（' + s['名'] + '）';
        box.append(n);
      });
      cell.append(box);
    }

    // ── 宫脚：宫名与宫干支一行，大限一行 ──
    //
    // 窄屏一格只有七十来像素，塞四段文字必然互相挤在一起。长生十二神与
    // 博士十二神移进宫位详情——读盘时几乎没人在格子里看这两项，
    // 而宫名、宫干支、大限区间是每次都要看的。
    const foot = el('div', 'zw-foot');
    const top = el('div', 'zwf-top');
    top.append(el('span', 'zwf-name', pal['宫名']));
    top.append(el('span', 'zwf-gz', pal['宫干支']));
    foot.append(top);
    foot.append(el('div', 'zwf-limit', pal['大限'].split('（')[0]));
    cell.append(foot);

    cell.addEventListener('click', () => openPalace(i));
    grid.append(cell);
  });

  grid.append(centerCell(c));
}

/** 一颗星的显示单元：星名 + 亮度 + 四化。 */
function starChip(s) {
  const cls = { 主星: 'major', 吉星: 'lucky', 煞星: 'malefic' }[s['类']] || 'minor';
  const n = el('span', 'zw-star ' + cls);
  n.append(el('span', null, s['名']));
  if (s['亮度']) n.append(el('span', 'zw-bright b-' + s['亮度'], s['亮度']));
  if (s['四化']) {
    // 「化禄」只取「禄」字：格子里一个字胜过两个字
    const k = s['四化'].slice(-1);
    n.append(el('i', 'sihua ' + k, k));
  }
  return n;
}

/** 盘心：出生与命盘的要目。 */
function centerCell(c) {
  const b = c['出生'];
  const p = c['命盘'];
  const box = el('div', 'zw-center');

  box.append(el('div', 'zwc-ju', p['五行局']));

  const r1 = el('div', 'zwc-row');
  r1.append(el('b', null, b['农历']));
  box.append(r1);

  const r2 = el('div', 'zwc-row');
  r2.append(b['时辰'] + '　' + b['阴阳'] + '　' + b['生肖'] + '年');
  box.append(r2);

  const r3 = el('div', 'zwc-row');
  r3.append('命主 ');
  r3.append(el('b', null, p['命主']));
  r3.append('　身主 ');
  r3.append(el('b', null, p['身主']));
  box.append(r3);

  const r4 = el('div', 'zwc-row');
  r4.append('大限' + p['大限排法']);
  box.append(r4);

  const sh = el('div', 'zwc-sihua');
  Object.keys(p['生年四化']).forEach((star) => {
    const kind = p['生年四化'][star].slice(-1);
    const chip = el('span', 'zw-star minor');
    chip.append(el('span', null, star));
    chip.append(el('i', 'sihua ' + kind, kind));
    sh.append(chip);
  });
  box.append(sh);

  return box;
}

// ── 宫位详情 ─────────────────────────────────────────────

(function initPalaceSheet() {
  const sheet = $('#palace-sheet');
  sheet.addEventListener('click', (e) => {
    if (e.target.closest('[data-close]')) closePalace();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !sheet.hidden) closePalace();
  });
})();

function closePalace() {
  $('#palace-sheet').hidden = true;
  document.body.classList.remove('sheet-open');
}

/** 打开第 i 宫（按地支序号）的详情。 */
function openPalace(i) {
  if (!chartData) return;
  const pal = chartData.chart['十二宫'][i];
  const body = $('#ps-body');
  body.innerHTML = '';

  $('#ps-title').textContent =
    pal['宫名'] + '　' + pal['宫干支'] + (pal['身宫'] ? '　· 身宫' : '');

  const sec = (label, node) => {
    const s = el('div', 'ps-sec');
    s.append(el('div', 'ps-label', label));
    s.append(node);
    body.append(s);
  };

  sec('这一宫管什么', el('p', 'ps-body-text dim', pal['宫位含义']));

  // 星曜按类分组列出，每颗带释义——「天姚」这种名字不解释等于没写
  const groups = [
    ['主星', pal['星曜'].filter((s) => s['类'] === '主星')],
    ['吉星', pal['星曜'].filter((s) => s['类'] === '吉星')],
    ['煞星', pal['星曜'].filter((s) => s['类'] === '煞星')],
    ['杂曜', pal['星曜'].filter((s) => s['类'] === '杂曜')],
  ];
  if (pal['借星'].length) groups.unshift(['借对宫主星（本宫无主星）', pal['借星']]);

  groups.forEach(([label, list]) => {
    if (!list.length) return;
    const box = el('div', 'ps-stars');
    list.forEach((s) => {
      const row = el('div', 'ps-star');
      const name = el('span', 'ps-star-name');
      name.append(s['名']);
      if (s['亮度']) name.append(el('span', 'zw-bright b-' + s['亮度'], s['亮度']));
      if (s['四化']) name.append(el('i', 'sihua ' + s['四化'].slice(-1), s['四化'].slice(-1)));
      row.append(name);
      // 释义随盘下发（chart.星曜释义），前端不另存一份表
      const mean = (chartData.chart['星曜释义'] || {})[s['名']];
      if (mean) row.append(el('span', 'ps-star-mean', mean));
      box.append(row);
    });
    sec(label, box);
  });

  // 三方四正：紫微论断的常规单位，不摊开就没有依据
  const tri = [0, 4, 6, 8].map((off) => chartData.chart['十二宫'][(i + off) % 12]);
  const triBox = el('div', 'ps-chips');
  ['本宫', '三合', '对宫', '三合'].forEach((label, k) => {
    const t = tri[k];
    const stars = t['星曜'].filter((s) => s['类'] === '主星')
      .map((s) => s['名'] + (s['亮度'] || '')).join(' ') || '空宫';
    triBox.append(el('span', 'tag', label + ' ' + t['宫名'] + '（' + stars + '）'));
  });
  sec('三方四正', triBox);

  const misc = el('div', 'ps-chips');
  [['大限', pal['大限']], ['小限起', pal['小限起'] + ' 岁'],
   ['长生', pal['长生十二神']], ['博士', pal['博士十二神']],
   ['岁前', pal['岁前']], ['将前', pal['将前']]].forEach(([k, v]) => {
    misc.append(el('span', 'tag', k + ' ' + v));
  });
  sec('限运与十二神', misc);

  $('#palace-sheet').hidden = false;
  document.body.classList.add('sheet-open');
  body.scrollTop = 0;
}

// ── 四化落宫 ─────────────────────────────────────────────

function renderSihua(analysis) {
  const box = $('#sihua-list');
  box.innerHTML = '';
  (analysis['生年四化落宫'] || []).forEach((x) => {
    const kind = x['化'].slice(-1);
    const item = el('div', 'sh-item');
    item.append(el('span', 'sh-badge ' + kind, x['化']));

    const main = el('div', 'sh-main');
    const head = el('div', 'sh-head');
    head.append(x['星'] + (x['亮度'] || '') + ' 落 ');
    head.append(el('span', null, palaceLabel(x['落宫']) + '（' + x['地支'] + '）'));
    main.append(head);
    main.append(el('p', 'sh-mean', x['释义']));
    item.append(main);
    box.append(item);
  });
}

const PALACE_NAMES = ['命宫', '兄弟', '夫妻', '子女', '财帛', '疾厄',
                      '迁移', '交友', '官禄', '田宅', '福德', '父母'];

/* 十二宫里只有「命宫」自带「宫」字，直接拼会得到「命宫宫」。
   后端有同名的 palace_label，前端也得有一份。

   非宫名原样返回：未入限时后端给的是「—」，套上「宫」字就成了「—宫」。
   出生日期填在未来时（表单允许到 2100 年）就会走到这一支。 */
function palaceLabel(name) {
  if (PALACE_NAMES.indexOf(name) < 0) return name;
  return /宫$/.test(name) ? name : name + '宫';
}

// ── 格局 ─────────────────────────────────────────────────

function renderPatterns(analysis) {
  const box = $('#pattern-list');
  box.innerHTML = '';
  const list = analysis['格局'] || [];
  $('#pattern-panel').hidden = !list.length;

  list.forEach((p) => {
    const card = el('div', 'pat ' + p['性质']);
    const head = el('div', 'pat-head');
    head.append(el('span', 'pat-name', p['格名']));
    head.append(el('span', 'pat-kind', p['性质']));
    head.append(el('span', 'pat-basis', p['依据']));
    card.append(head);
    card.append(el('p', 'pat-note', p['说明']));
    box.append(card);
  });
}

// ── 大限 ─────────────────────────────────────────────────

function renderLimits(chart, years) {
  const p = chart['命盘'];
  $('#limit-start').textContent =
    '大限' + p['大限排法'] + '　' + p['五行局'] +
    '，自命宫起，每宫十年（起限虚岁即局数）';

  const strip = $('#limit-strip');
  strip.innerHTML = '';
  const current = years && years[0] ? years[0]['所行大限'] : '';

  // 大限按行进顺序排（顺行则地支递增、逆行则递减），不按地支序——
  // 用户想看的是「先走哪一步」，不是地支表
  const palaces = chart['十二宫'].slice().sort(
    (a, b) => parseInt(a['大限'], 10) - parseInt(b['大限'], 10));

  palaces.forEach((pal) => {
    const cell = el('div', 'luck-cell');
    if (current && current.indexOf(pal['宫名']) === 0) {
      cell.classList.add('current');
    }
    cell.append(el('div', 'lg', pal['宫名']));
    const own = pal['星曜'].filter((s) => s['类'] === '主星')
      .map((s) => s['名']);
    const stars = own.length
      ? own.join('')
      : (pal['借星'].length
          ? '借' + pal['借星'].map((s) => s['名']).join('、')
          : '空宫');
    cell.append(el('div', 'lt', stars));
    cell.append(el('div', 'ly', pal['大限'].replace(' 虚岁', '')));
    strip.append(cell);
  });

  const cur = strip.querySelector('.current');
  if (cur) cur.scrollIntoView({ block: 'nearest', inline: 'center' });
}

// ── 流年 ─────────────────────────────────────────────────

/* 今年单独放大，后两年压成小卡——注意力该给当下，
   但把后两年摆出来能让人意识到「这是有时间性的东西」。 */
function renderYears(years) {
  const box = $('#years');
  box.innerHTML = '';
  if (!years || !years.length) return;

  const cur = years[0];
  const head = el('div', 'year-now');

  const top = el('div', 'yn-top');
  top.append(el('span', 'yn-year', cur['年份'] + ' 年'));
  top.append(el('span', 'yn-gz', cur['流年干支']));
  top.append(el('span', 'yn-palace', '流年入' + palaceLabel(cur['流年宫'])));
  head.append(top);

  head.append(el('p', 'yn-theme', cur['流年宫含义']));

  const meta = el('div', 'yn-meta');
  meta.append(el('span', null, '所行大限 ' + cur['所行大限']));
  meta.append(el('span', null, '大限主星 ' + (cur['大限主星'] || []).join(' ')));
  meta.append(el('span', null, '小限 ' + palaceLabel(cur['小限宫'])));
  meta.append(el('span', null, '虚岁 ' + cur['虚岁']));
  head.append(meta);

  // 流年四化落在哪个宫，是「今年这件事在哪一块」最直接的答案
  const sh = el('div', 'yn-sihua');
  (cur['流年四化'] || []).forEach((x) => {
    const kind = x['化'].slice(-1);
    const chip = el('span', 'yn-sh');
    chip.append(el('i', 'sihua ' + kind, kind));
    chip.append(el('b', null, x['星']));
    chip.append(' → ' + palaceLabel(x['落宫']));
    sh.append(chip);
  });
  if (sh.children.length) head.append(sh);
  box.append(head);

  const rest = el('div', 'year-rest');
  years.slice(1).forEach((y) => {
    const c = el('div', 'year-mini');
    c.append(el('div', 'ym-year', String(y['年份'])));
    c.append(el('div', 'ym-gz', y['流年干支']));
    c.append(el('div', 'ym-god', '入' + palaceLabel(y['流年宫'])));
    rest.append(c);
  });
  if (rest.children.length) box.append(rest);
}

// ── 待定论 ───────────────────────────────────────────────

/* 整条漏斗里唯一让用户想到「我的情况比较特殊」的地方。
   点任意一条 = 把命盘摘要和这个问题一起复制好。 */
function renderInquiry(items) {
  const panel = $('#inquiry-panel');
  const box = $('#inquiry-list');
  box.innerHTML = '';
  if (!items || !items.length) { panel.hidden = true; return; }
  panel.hidden = false;

  items.forEach((q) => {
    const card = el('div', 'inq');
    card.append(el('div', 'inq-title', q['标题']));
    card.append(el('p', 'inq-fact', q['事实']));
    card.append(el('p', 'inq-fork', q['两可']));

    const ask = el('button', 'inq-ask');
    ask.type = 'button';
    ask.append(el('span', 'inq-q', q['问题']));
    ask.append(el('span', 'inq-go', '带着这个问题问 →'));
    ask.addEventListener('click', () => askQuestion(q['问法'] || q['问题']));
    card.append(ask);
    box.append(card);
  });
}
