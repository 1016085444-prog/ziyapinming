/* 子牙品命 — 前端。无构建步骤，原生 ES module 语法即可。 */

'use strict';

/* 出生地经度决定真太阳时校正量：1° = 4 分钟，而一个时辰是 120 分钟。
   乌鲁木齐用北京时间时偏差近两小时，足以整体错一到两个时辰。

   做成省 → 市两级，是因为让用户填经纬度等于把题甩回给用户，没人知道自己
   的出生地经度。省内经度跨度通常 3–8°（最大误差约 ±15 分钟），所以选到
   省会一级对绝大多数人已经够用，再细的差异不足以改变时柱——这也是这里
   不提供「自定义经度」的原因：它只会制造精确的幻觉。

   条目为 [市名, 经度] 或 [市名, 经度, 时区]（时区省略即 UTC+8）。 */
const REGIONS = [
  ['北京', [['北京', 116.41]]],
  ['天津', [['天津', 117.20]]],
  ['上海', [['上海', 121.47]]],
  ['重庆', [['重庆', 106.55]]],
  ['河北', [['石家庄', 114.51], ['唐山', 118.18], ['保定', 115.48],
            ['邯郸', 114.54], ['张家口', 114.89], ['秦皇岛', 119.60],
            ['廊坊', 116.70], ['沧州', 116.86]]],
  ['山西', [['太原', 112.55], ['大同', 113.30], ['临汾', 111.52],
            ['运城', 111.00], ['长治', 113.11]]],
  ['内蒙古', [['呼和浩特', 111.75], ['包头', 109.84], ['鄂尔多斯', 109.99],
              ['赤峰', 118.89], ['通辽', 122.24], ['呼伦贝尔', 119.77]]],
  ['辽宁', [['沈阳', 123.43], ['大连', 121.62], ['鞍山', 122.99],
            ['锦州', 121.13], ['丹东', 124.38]]],
  ['吉林', [['长春', 125.32], ['吉林市', 126.55], ['延吉', 129.51],
            ['四平', 124.35]]],
  ['黑龙江', [['哈尔滨', 126.53], ['齐齐哈尔', 123.92], ['大庆', 125.10],
              ['牡丹江', 129.63], ['佳木斯', 130.32]]],
  ['江苏', [['南京', 118.80], ['苏州', 120.58], ['无锡', 120.30],
            ['常州', 119.95], ['徐州', 117.18], ['南通', 120.86],
            ['扬州', 119.42], ['盐城', 120.16], ['连云港', 119.22]]],
  ['浙江', [['杭州', 120.15], ['宁波', 121.55], ['温州', 120.70],
            ['绍兴', 120.58], ['嘉兴', 120.76], ['金华', 119.65],
            ['台州', 121.43], ['湖州', 120.09]]],
  ['安徽', [['合肥', 117.28], ['芜湖', 118.38], ['蚌埠', 117.39],
            ['安庆', 117.05], ['阜阳', 115.81]]],
  ['福建', [['福州', 119.30], ['厦门', 118.09], ['泉州', 118.59],
            ['漳州', 117.65], ['莆田', 119.01]]],
  ['江西', [['南昌', 115.89], ['赣州', 114.94], ['九江', 115.99],
            ['上饶', 117.97], ['宜春', 114.42]]],
  ['山东', [['济南', 117.00], ['青岛', 120.38], ['烟台', 121.39],
            ['潍坊', 119.16], ['临沂', 118.35], ['淄博', 118.05],
            ['济宁', 116.59], ['泰安', 117.09]]],
  ['河南', [['郑州', 113.62], ['洛阳', 112.45], ['南阳', 112.53],
            ['新乡', 113.93], ['信阳', 114.09], ['安阳', 114.39],
            ['商丘', 115.65], ['开封', 114.31]]],
  ['湖北', [['武汉', 114.30], ['宜昌', 111.29], ['襄阳', 112.14],
            ['荆州', 112.24], ['黄石', 115.04]]],
  ['湖南', [['长沙', 112.94], ['株洲', 113.13], ['衡阳', 112.61],
            ['岳阳', 113.13], ['常德', 111.70], ['湘潭', 112.94]]],
  ['广东', [['广州', 113.26], ['深圳', 114.06], ['东莞', 113.75],
            ['佛山', 113.12], ['珠海', 113.55], ['中山', 113.39],
            ['惠州', 114.41], ['汕头', 116.68], ['湛江', 110.36],
            ['江门', 113.09]]],
  ['广西', [['南宁', 108.37], ['柳州', 109.42], ['桂林', 110.29],
            ['北海', 109.12], ['玉林', 110.16]]],
  ['海南', [['海口', 110.20], ['三亚', 109.51]]],
  ['四川', [['成都', 104.07], ['绵阳', 104.68], ['宜宾', 104.63],
            ['泸州', 105.44], ['南充', 106.11], ['攀枝花', 101.72]]],
  ['贵州', [['贵阳', 106.63], ['遵义', 106.93], ['六盘水', 104.83]]],
  ['云南', [['昆明', 102.83], ['曲靖', 103.80], ['大理', 100.23],
            ['丽江', 100.23]]],
  ['西藏', [['拉萨', 91.11], ['日喀则', 88.88], ['昌都', 97.17]]],
  ['陕西', [['西安', 108.94], ['宝鸡', 107.24], ['咸阳', 108.71],
            ['汉中', 107.03], ['榆林', 109.73]]],
  ['甘肃', [['兰州', 103.82], ['天水', 105.72], ['张掖', 100.45],
            ['酒泉', 98.51]]],
  ['青海', [['西宁', 101.78], ['格尔木', 94.90]]],
  ['宁夏', [['银川', 106.23], ['石嘴山', 106.38]]],
  ['新疆', [['乌鲁木齐', 87.62], ['喀什', 75.99], ['伊宁', 81.32],
            ['克拉玛依', 84.89], ['哈密', 93.51], ['阿克苏', 80.26]]],
  ['香港', [['香港', 114.17]]],
  ['澳门', [['澳门', 113.55]]],
  ['台湾', [['台北', 121.52], ['高雄', 120.31], ['台中', 120.68]]],
  ['海外', [['东京', 139.69, 9], ['首尔', 126.98, 9], ['新加坡', 103.82, 8],
            ['吉隆坡', 101.69, 8], ['曼谷', 100.50, 7], ['悉尼', 151.21, 10],
            ['洛杉矶', -118.24, -8], ['旧金山', -122.42, -8],
            ['纽约', -74.01, -5], ['温哥华', -123.12, -8],
            ['多伦多', -79.38, -5], ['伦敦', -0.13, 0], ['巴黎', 2.35, 1],
            ['柏林', 13.40, 1]]],
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

/* 出生地摊平成一维可搜索列表。
   放弃「省 → 市」两级下拉有两个原因：一是微信内置浏览器对长 select
   下拉有渲染问题，而这里正卡在唯一的转化路径上；二是两级要求用户先想起
   「苏州属江苏」，摊平后直接搜城市名，少一步操作也少一层认知负担。 */
const PLACES = [];
REGIONS.forEach(function (region) {
  const prov = region[0];
  region[1].forEach(function (c) {
    PLACES.push({
      city: c[0],
      prov: prov,
      // 直辖市与港澳的省市同名，不重复显示
      label: prov === c[0] ? c[0] : prov + ' · ' + c[0],
      plain: prov === c[0] ? c[0] : prov + c[0],
      lon: c[1],
      tz: c[2] === undefined ? 8 : c[2],
    });
  });
});

const HOT = ['北京', '上海', '广州', '深圳', '成都', '杭州',
             '武汉', '西安', '重庆', '南京', '天津', '长沙'];

let chosenPlace = PLACES.find(function (p) { return p.city === '上海'; }) || PLACES[0];

(function initPlacePicker() {
  const btn = $('#place-btn');
  const label = $('#place-label');
  const sheet = $('#place-sheet');
  const search = $('#place-search');
  const list = $('#place-list');

  function paint() { label.textContent = chosenPlace.label; }

  function row(p) {
    const b = el('button', 'place-row', p.label);
    b.type = 'button';
    if (p === chosenPlace) b.classList.add('on');
    b.addEventListener('click', function () {
      chosenPlace = p;
      paint();
      close();
    });
    return b;
  }

  function render(q) {
    q = (q || '').trim();
    list.innerHTML = '';

    if (!q) {
      // 无搜索词时先摆常用城市：为了选北京也要滚过三十几个省不合理
      list.append(el('div', 'sheet-group', '常用'));
      HOT.forEach(function (n) {
        const hit = PLACES.find(function (p) { return p.city === n; });
        if (hit) list.append(row(hit));
      });
      list.append(el('div', 'sheet-group', '全部'));
      PLACES.forEach(function (p) { list.append(row(p)); });
      return;
    }

    const hits = PLACES.filter(function (p) {
      return p.city.indexOf(q) >= 0 || p.prov.indexOf(q) >= 0;
    });
    if (!hits.length) {
      list.append(el('p', 'sheet-empty',
        '没找到「' + q + '」。可以试省份名，或选同省最近的城市——' +
        '省内经度差通常不足以改变时辰。'));
      return;
    }
    hits.forEach(function (p) { list.append(row(p)); });
  }

  function open() {
    sheet.hidden = false;
    document.body.classList.add('sheet-open');
    search.value = '';
    render('');
    list.scrollTop = 0;
    // 故意不自动聚焦搜索框：iOS 会立刻弹出键盘挡掉半屏列表，
    // 而多数人是来浏览常用城市的，不是来打字的。
  }

  function close() {
    sheet.hidden = true;
    document.body.classList.remove('sheet-open');
  }

  btn.addEventListener('click', open);
  sheet.addEventListener('click', function (e) {
    if (e.target.closest('[data-close]')) close();
  });
  search.addEventListener('input', function () { render(search.value); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !sheet.hidden) close();
  });

  paint();
})();

/** 读取当前选中的出生地。返回 { name, longitude, tz }。 */
function selectedPlace() {
  return {
    name: chosenPlace.plain,
    longitude: chosenPlace.lon,
    tz: chosenPlace.tz,
  };
}

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

  const place = selectedPlace();

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
        longitude: place.longitude,
        tz_offset: place.tz,
        use_true_solar_time: form.tst.checked,
        late_zi_shifts_day: form.latezi.checked,
        adjust_china_dst: form.dst.checked,
      }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || '排盘失败');

    const data = await res.json();

    // 排盘是本地计算，几毫秒就返回。这里刻意留一个推演的停顿——
    // 秒出结果会让人觉得只是查了张表，反而折损可信度。
    // 嫌慢就把 CAST_BEAT 调成 0。
    const wait = CAST_BEAT - (Date.now() - startedAt);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));

    render(data, place.name);
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

function render(data, placeName) {
  const chart = data.chart;
  const bazi = chart['四柱'].map((p) => p['干支']).join(' ');
  const b = chart['出生'];
  state.summary =
    '八字：' + bazi + '\n' +
    '（' + b['性别'] + '，' + b['标准时'] +
    (placeName ? ' 生于' + placeName : '') + '）';

  renderMeta(chart);
  renderPillars(chart);
  renderScores(data.scores);
  renderElements(data.analysis);
  renderLuck(chart, data.years);
  renderShensha(chart);
}

/* 五维雷达图。半径直接按分数比例走（分数区间 38–96，映射到 38%–96% 半径），
   不做二次拉伸——拉伸会把差距夸大，看着刺激但不诚实。 */
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
  box.append(line('公历', b['标准时'] + '（' + b['性别'] + '）'
                          + (b['已回退夏令时'] ? ' · 已回退夏令时 1 小时' : '')));
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
