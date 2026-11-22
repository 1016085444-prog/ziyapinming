/* 每日精选里的统计图：柱状图、折线图、温度计、横向条、哑铃图、走势小图。纯 SVG，无依赖。
 *
 * 约定（遵循数据可视化规范）：
 * - 先定图的形式再上色：比大小用柱、看变化用线、单个读数用温度计 / 数字，绝不做双纵轴（两种量纲就上下分两格）；
 * - 颜色只做一件事：分序列用固定顺序的 --s1/--s2/--s3；分正负用涨跌色 --up/--down；温度用蓝 ↔ 红、中间灰；
 * - 细柱（≤24px）、数据端 4px 圆角、基线端直角；折线 2px；网格和坐标轴是退在后面的实线细线；
 * - 文字一律用文字色，颜色只在图形上；两条以上序列一定有图例，数值只标要紧的那几个，其余交给坐标轴和悬停提示；
 * - 每张图都能悬停 / 键盘聚焦看数值，并且带一张「看数字」的表——提示只是增强，不是唯一的入口；
 * - 标签一律用 textContent 写入。
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  function S(tag, attrs, text) {
    var e = document.createElementNS(NS, tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k]); });
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function H(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function add(p) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) p.appendChild(arguments[i]); return p; }

  function niceTicks(min, max, count) {
    if (!(isFinite(min) && isFinite(max))) return [];
    if (max - min < 1e-12) { max = min + Math.abs(min || 1) * 0.5; min = min - Math.abs(min || 1) * 0.5; }
    var raw = (max - min) / Math.max(1, count);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    var step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    var out = [];
    for (var v = Math.ceil(min / step - 1e-9) * step; v <= max + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  function pctFmt(d) {
    return function (v) {
      if (v === null || v === undefined || !isFinite(v)) return '—';
      var x = v * 100;
      return (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d === undefined ? 1 : d) + '%';
    };
  }

  /* 图的外壳：标题、图例、画布、悬停提示、「看数字」的表。render(width) 负责画，宽度变了会重画。 */
  function figure(opts, render) {
    var fig = H('figure', 'viz');
    if (opts.title) add(fig, add(H('figcaption', 'viz-cap'), H('span', 'viz-title', opts.title), opts.sub ? H('span', 'viz-sub', opts.sub) : null));
    var legend = H('div', 'viz-legend');
    var stage = H('div', 'viz-stage');
    var tip = H('div', 'viz-tip');
    tip.setAttribute('role', 'status');
    add(fig, legend, add(stage, tip));
    if (opts.note) add(fig, H('div', 'viz-note', opts.note));
    var api = {
      fig: fig, stage: stage, legend: legend,
      setLegend: function (items) {
        legend.replaceChildren();
        if (!items || items.length < 2) { legend.hidden = true; return; }
        legend.hidden = false;
        items.forEach(function (it) {
          add(legend, add(H('span', 'viz-key'), H('i', 'viz-swatch ' + (it.shape || 'box') + ' ' + it.cls), H('span', null, it.name)));
        });
      },
      showTip: function (rows, title, x, y) {
        tip.replaceChildren();
        if (title) add(tip, H('div', 'viz-tip-title', title));
        rows.forEach(function (r) {
          add(tip, add(H('div', 'viz-tip-row'), r.cls ? H('i', 'viz-swatch line ' + r.cls) : null, H('strong', null, r.value), H('span', null, r.label)));
        });
        tip.style.display = 'block';
        var w = tip.offsetWidth, sw = stage.clientWidth;
        tip.style.left = Math.max(0, Math.min(sw - w, x - w / 2)) + 'px';
        tip.style.top = Math.max(0, y - tip.offsetHeight - 10) + 'px';
      },
      hideTip: function () { tip.style.display = 'none'; }
    };
    var last = 0;
    function draw() {
      var w = Math.max(280, Math.round(stage.clientWidth || fig.clientWidth || 640));
      if (w === last) return;
      last = w;
      Array.prototype.slice.call(stage.querySelectorAll('svg')).forEach(function (n) { n.remove(); });
      stage.insertBefore(render(w, api), tip);
    }
    if (window.ResizeObserver) new ResizeObserver(function () { draw(); }).observe(stage);
    setTimeout(draw, 0);
    if (opts.table) add(fig, tableView(opts.table));
    return fig;
  }

  function tableView(t) {
    var d = H('details', 'viz-table small');
    add(d, H('summary', null, '看数字'));
    var table = H('table', 'tbl');
    var tr = H('tr');
    t.head.forEach(function (x, i) { var th = H('th', i ? 'n' : '', x); add(tr, th); });
    add(table, add(H('thead'), tr));
    var tb = H('tbody');
    t.rows.forEach(function (r) {
      var row = H('tr');
      r.forEach(function (x, i) { add(row, H('td', i ? 'n' : '', x)); });
      add(tb, row);
    });
    add(d, add(H('div', 'table-wrap'), add(table, tb)));
    return d;
  }

  function colPath(x, w, y0, y1) {
    /* 一根柱：y0 是基线（直角），y1 是数据端（4px 圆角）。 */
    var r = Math.min(4, w / 2, Math.abs(y1 - y0));
    var s = y1 < y0 ? 1 : -1;
    return 'M' + x + ',' + y0 + 'L' + x + ',' + (y1 + s * r) + 'Q' + x + ',' + y1 + ' ' + (x + r) + ',' + y1 +
      'L' + (x + w - r) + ',' + y1 + 'Q' + (x + w) + ',' + y1 + ' ' + (x + w) + ',' + (y1 + s * r) + 'L' + (x + w) + ',' + y0 + 'Z';
  }

  function bindMark(node, api, rowsFn, title) {
    node.setAttribute('tabindex', '0');
    node.classList.add('viz-mark');
    function show() {
      var b = node.getBoundingClientRect(), s = api.stage.getBoundingClientRect();
      api.showTip(rowsFn(), title, b.left + b.width / 2 - s.left, b.top - s.top);
    }
    node.addEventListener('pointerenter', show);
    node.addEventListener('focus', show);
    node.addEventListener('pointerleave', api.hideTip);
    node.addEventListener('blur', api.hideTip);
  }

  /* 柱状图。
   * o.categories: 横轴上的类别；o.series: [{name, values, cls}]（一条序列时可以不给 cls）；
   * o.sign: true → 按正负上色（涨跌色），只用于单序列；o.highlight: 要强调的类别下标（加底色、标数值）；
   * o.fmt: 数值格式；o.height；o.every: 横轴每隔几个标一次。 */
  function columns(o) {
    var fmt = o.fmt || pctFmt(1);
    var series = o.series;
    var cats = o.categories;
    var table = o.table === false ? null : {
      head: [o.catLabel || ''].concat(series.map(function (s) { return s.name; })),
      rows: cats.map(function (c, i) { return [c].concat(series.map(function (s) { return fmt(s.values[i]); })); })
    };
    return figure({ title: o.title, sub: o.sub, note: o.note, table: table }, function (W, api) {
      api.setLegend(series.length > 1 ? series.map(function (s, k) { return { name: s.name, cls: s.cls || ('s' + (k + 1)) }; }) : null);
      var Hh = o.height || 200, padL = 56, padR = 8, padT = 14, padB = 26;
      var all = [];
      series.forEach(function (s) { s.values.forEach(function (v) { if (v !== null && v !== undefined && isFinite(v)) all.push(v); }); });
      var lo = Math.min(0, Math.min.apply(null, all)), hi = Math.max(0, Math.max.apply(null, all));
      var ticks = niceTicks(lo, hi, 4);
      lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
      var svg = S('svg', { width: W, height: Hh, viewBox: '0 0 ' + W + ' ' + Hh, role: 'img', 'aria-label': (o.title || '柱状图') + '。数值见下方「看数字」' });
      var pw = W - padL - padR, ph = Hh - padT - padB;
      var y = function (v) { return padT + (hi - v) / (hi - lo || 1) * ph; };
      ticks.forEach(function (t) {
        add(svg, S('line', { x1: padL, x2: W - padR, y1: y(t), y2: y(t), class: t === 0 ? 'viz-axis' : 'viz-grid' }),
          S('text', { x: padL - 6, y: y(t) + 4, class: 'viz-tick', 'text-anchor': 'end' }, fmt(t)));
      });
      var band = pw / cats.length;
      var n = series.length;
      var gap = 2;
      var bw = Math.max(2, Math.min(24, (band * 0.72 - gap * (n - 1)) / n));
      var group = bw * n + gap * (n - 1);
      var longest = cats.reduce(function (m, c) { return Math.max(m, String(c).length); }, 0);
      var every = o.every || Math.max(1, Math.ceil((longest * 6.6 + 10) / band));
      cats.forEach(function (c, i) {
        var x0 = padL + band * i + (band - group) / 2;
        if (o.highlight === i) add(svg, S('rect', { x: padL + band * i + 1, y: padT, width: band - 2, height: ph, class: 'viz-hl' }));
        series.forEach(function (s, k) {
          var v = s.values[i];
          if (v === null || v === undefined || !isFinite(v)) return;
          var cls = o.sign ? (v >= 0 ? 'up' : 'down') : (s.cls || ('s' + (k + 1)));
          var bar = S('path', { d: colPath(x0 + k * (bw + gap), bw, y(0), y(v)), class: 'viz-fill ' + cls });
          bindMark(bar, api, function () {
            return series.map(function (ss, kk) {
              return { cls: series.length > 1 ? (ss.cls || ('s' + (kk + 1))) : null, value: fmt(ss.values[i]), label: series.length > 1 ? ss.name : (o.valueLabel || '') };
            }).concat(o.extra ? o.extra(i) : []);
          }, c);
          add(svg, bar);
        });
        var nearHl = o.highlight !== undefined && o.highlight !== null && o.highlight >= 0 && i !== o.highlight && Math.abs(i - o.highlight) < every;
        if ((i % every === 0 && !nearHl) || o.highlight === i) add(svg, S('text', { x: padL + band * (i + 0.5), y: Hh - 8, class: 'viz-tick' + (o.highlight === i ? ' strong' : ''), 'text-anchor': 'middle' }, c));
        if (o.highlight === i && n === 1) {
          var hv = series[0].values[i];
          if (hv !== null && isFinite(hv)) add(svg, S('text', { x: padL + band * (i + 0.5), y: y(hv) + (hv >= 0 ? -5 : 13), class: 'viz-label', 'text-anchor': 'middle' }, fmt(hv)));
        }
      });
      return svg;
    });
  }

  /* 折线图，可以上下分几格（每格自己的纵轴——两种量纲不共用一个轴）。
   * o.x: 横轴标签；o.panels: [{series: [{name, values, cls}], fmt, height, bands: [{y, label}], zero: 是否包含 0, log}]。 */
  function lines(o) {
    var x = o.x;
    var panels = o.panels;
    var flat = [];
    panels.forEach(function (p) { p.series.forEach(function (s) { flat.push({ p: p, s: s }); }); });
    var table = o.table === false ? null : {
      head: [o.xLabel || ''].concat(flat.map(function (f) { return f.s.name; })),
      rows: x.map(function (c, i) { return [c].concat(flat.map(function (f) { return (f.p.fmt || String)(f.s.values[i]); })); }).filter(function (r, i) {
        return !o.tableEvery || i % o.tableEvery === 0 || i === x.length - 1;
      })
    };
    return figure({ title: o.title, sub: o.sub, note: o.note, table: table }, function (W, api) {
      var multi = flat.length > 1 && panels.some(function (p) { return p.series.length > 1; });
      api.setLegend(multi ? panels[0].series.map(function (s, k) { return { name: s.name, cls: s.cls || ('s' + (k + 1)), shape: 'line' }; }) : null);
      var padL = 50, padT = 12, padB = 24, gapP = 18;
      var padR = panels.some(function (p) { return p.series.length > 1 && p.series.length <= 4 && p.endLabels !== false; }) ? 86 : 12;
      var total = padT + padB + gapP * (panels.length - 1);
      panels.forEach(function (p) { total += p.height || 170; });
      var svg = S('svg', { width: W, height: total, viewBox: '0 0 ' + W + ' ' + total, role: 'img', tabindex: '0', 'aria-label': (o.title || '折线图') + '。数值见下方「看数字」' });
      var pw = W - padL - padR;
      var n = x.length;
      var X = function (i) { return padL + (n <= 1 ? pw / 2 : pw * i / (n - 1)); };
      var top = padT;
      var layouts = [];
      panels.forEach(function (p, pi) {
        var ph = p.height || 170;
        var vals = [];
        p.series.forEach(function (s) { s.values.forEach(function (v) { if (v !== null && v !== undefined && isFinite(v)) vals.push(v); }); });
        (p.bands || []).forEach(function (b) { vals.push(b.y); });
        var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
        if (p.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
        if (p.min !== undefined) lo = p.min;
        if (p.max !== undefined) hi = p.max;
        var ticks = niceTicks(lo, hi, 4);
        if (p.min === undefined) lo = Math.min(lo, ticks[0]);
        if (p.max === undefined) hi = Math.max(hi, ticks[ticks.length - 1]);
        var fmt = p.fmt || String;
        var Y = (function (t0, h, a, b) { return function (v) { return t0 + (b - v) / (b - a || 1) * h; }; })(top, ph, lo, hi);
        ticks.forEach(function (t) {
          add(svg, S('line', { x1: padL, x2: padL + pw, y1: Y(t), y2: Y(t), class: (p.zero && t === 0) ? 'viz-axis' : 'viz-grid' }),
            S('text', { x: padL - 6, y: Y(t) + 4, class: 'viz-tick', 'text-anchor': 'end' }, fmt(t)));
        });
        (p.bands || []).forEach(function (b) {
          add(svg, S('line', { x1: padL, x2: padL + pw, y1: Y(b.y), y2: Y(b.y), class: 'viz-ref' }),
            S('text', { x: padL + 4, y: Y(b.y) - 4, class: 'viz-tick' }, b.label));
        });
        if (p.label) add(svg, S('text', { x: padL + pw, y: top + 10, class: 'viz-tick', 'text-anchor': 'end' }, p.label));
        var ends = [];
        p.series.forEach(function (s, k) {
          var cls = s.cls || ('s' + (k + 1));
          var d = '', pen = false, lastI = -1;
          s.values.forEach(function (v, i) {
            if (v === null || v === undefined || !isFinite(v)) { pen = false; return; }
            d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1);
            pen = true; lastI = i;
          });
          if (p.area && p.series.length === 1 && lastI >= 0) {
            var first = s.values.findIndex(function (v) { return v !== null && v !== undefined && isFinite(v); });
            add(svg, S('path', { d: d + 'L' + X(lastI).toFixed(1) + ',' + Y(lo) + 'L' + X(first).toFixed(1) + ',' + Y(lo) + 'Z', class: 'viz-area ' + cls }));
          }
          add(svg, S('path', { d: d, class: 'viz-line ' + cls }));
          if (lastI >= 0) {
            add(svg, S('circle', { cx: X(lastI), cy: Y(s.values[lastI]), r: 4, class: 'viz-dot ' + cls }));
            ends.push({ y: Y(s.values[lastI]), name: s.name, v: s.values[lastI] });
          }
        });
        if (p.series.length > 1 && p.series.length <= 4 && p.endLabels !== false) {
          ends.sort(function (a, b) { return a.y - b.y; });
          var sep = ends.every(function (e, i) { return i === 0 || e.y - ends[i - 1].y >= 13; });
          if (sep) ends.forEach(function (e) { add(svg, S('text', { x: padL + pw + 8, y: e.y + 4, class: 'viz-label' }, e.name)); });
        } else if (p.series.length === 1 && ends.length && p.endValue !== false) {
          add(svg, S('text', { x: Math.min(W - 4, padL + pw + 6), y: ends[0].y - 8, class: 'viz-label', 'text-anchor': 'end' }, fmt(ends[0].v)));
        }
        layouts.push({ p: p, Y: Y, top: top, h: ph, fmt: fmt });
        top += ph + gapP;
      });
      /* 横轴标签：按实际宽度排，前一个的右边和后一个的左边至少隔开 8px，不重叠 */
      var lastRight = -1e9;
      for (var i = 0; i < n; i++) {
        var label = String(x[i]);
        var w = label.length * 6.6;
        var anchor = 'middle', left = X(i) - w / 2;
        if (i === 0) { anchor = 'start'; left = X(i); }
        else if (left + w > W - 2) {
          if (i < n - 1) continue;
          anchor = 'end'; left = X(i) - w;   /* 最后一个（最新的日期）靠右对齐，不出界 */
        }
        if (left < lastRight + 8) continue;
        add(svg, S('text', { x: X(i), y: total - 8, class: 'viz-tick', 'text-anchor': anchor }, label));
        lastRight = left + w;
      }
      /* 十字光标：对齐最近的那个点，提示里列出这一列所有序列的数值 */
      var cross = S('line', { y1: padT, y2: total - padB, class: 'viz-cross', visibility: 'hidden' });
      add(svg, cross);
      var cur = -1;
      function at(i) {
        cur = Math.max(0, Math.min(n - 1, i));
        cross.setAttribute('x1', X(cur)); cross.setAttribute('x2', X(cur)); cross.setAttribute('visibility', 'visible');
        var rows = [];
        layouts.forEach(function (L) {
          L.p.series.forEach(function (s, k) {
            rows.push({ cls: flat.length > 1 ? (s.cls || ('s' + (k + 1))) : null, value: L.fmt(s.values[cur]), label: flat.length > 1 || o.valueLabel ? s.name : '' });
          });
        });
        api.showTip(rows, x[cur], X(cur), padT + 6);
      }
      function leave() { cross.setAttribute('visibility', 'hidden'); api.hideTip(); cur = -1; }
      svg.addEventListener('pointermove', function (ev) {
        var r = svg.getBoundingClientRect();
        at(Math.round((ev.clientX - r.left - padL) / (pw || 1) * (n - 1)));
      });
      svg.addEventListener('pointerleave', leave);
      svg.addEventListener('blur', leave);
      svg.addEventListener('keydown', function (ev) {
        if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') { ev.preventDefault(); at((cur < 0 ? n - 1 : cur) + (ev.key === 'ArrowLeft' ? -1 : 1)); }
      });
      return svg;
    });
  }

  /* 温度计：一条分成几档的轨道，上面一个指针。o.value 0–100；o.zones: [{to, label, cls}]。 */
  function meter(o) {
    var wrap = H('div', 'viz-meter');
    var track = H('div', 'viz-meter-track');
    var from = 0;
    o.zones.forEach(function (z) {
      var seg = H('div', 'viz-meter-seg ' + z.cls + (o.value >= from && o.value < z.to ? ' on' : ''));
      seg.style.width = (z.to - from) + '%';
      seg.title = from + '–' + z.to + '：' + z.label;
      add(seg, H('span', null, z.label));
      add(track, seg);
      from = z.to;
    });
    var pin = H('div', 'viz-meter-pin');
    pin.style.left = Math.max(0, Math.min(100, o.value)) + '%';
    add(pin, H('b', null, o.valueText || String(Math.round(o.value))));
    var scale = H('div', 'viz-meter-scale');
    [0, 20, 40, 60, 80, 100].forEach(function (t) { var s = H('span', null, String(t)); s.style.left = t + '%'; add(scale, s); });
    wrap.setAttribute('role', 'img');
    wrap.setAttribute('aria-label', (o.label || '读数') + ' ' + Math.round(o.value) + '（0–100）');
    return add(wrap, add(H('div', 'viz-meter-box'), track, pin), scale);
  }

  /* 一行一个比例：名字、条、数字（条对齐）。rows: [{label, value(0–100), text, cls}] */
  function meterList(rows) {
    var box = H('div', 'viz-mlist');
    rows.forEach(function (r) {
      var bar = H('div', 'viz-mbar');
      var fill = H('i', r.cls || 's1');
      fill.style.width = Math.max(0, Math.min(100, r.value)) + '%';
      add(box, add(H('div', 'viz-mrow'), H('span', 'viz-mname', r.label), add(bar, fill), H('span', 'viz-mval', r.text)));
    });
    return box;
  }

  /* 横向条（可正可负），一行一个，数值标在条的末端。rows: [{label, value, note}] */
  function hbars(o) {
    var fmt = o.fmt || pctFmt(0);
    var rows = o.rows;
    return figure({ title: o.title, sub: o.sub, note: o.note, table: { head: [o.catLabel || ''].concat(o.valueLabel || '数值', o.noteLabel ? [o.noteLabel] : []), rows: rows.map(function (r) { return [r.label, fmt(r.value)].concat(o.noteLabel ? [r.note || ''] : []); }) } }, function (W, api) {
      var rowH = 24, padT = 4, nameW = Math.min(150, Math.max(84, W * 0.26));
      var Hh = padT * 2 + rowH * rows.length;
      var vals = rows.map(function (r) { return r.value; });
      var lo = Math.min(0, Math.min.apply(null, vals)), hi = Math.max(0, Math.max.apply(null, vals));
      /* 负数的数字标在条的左端外面，所以有负数时在名字和条之间留一段空，不和名字挤在一起 */
      var gutL = lo < 0 ? 52 : 0, padR = hi > 0 ? 56 : 8;
      var pw = W - nameW - gutL - padR;
      var Xv = function (v) { return nameW + gutL + (v - lo) / (hi - lo || 1) * pw; };
      var svg = S('svg', { width: W, height: Hh, viewBox: '0 0 ' + W + ' ' + Hh, role: 'img', 'aria-label': (o.title || '横向条形图') + '。数值见下方「看数字」' });
      add(svg, S('line', { x1: Xv(0), x2: Xv(0), y1: padT, y2: Hh - padT, class: 'viz-axis' }));
      rows.forEach(function (r, i) {
        var cy = padT + rowH * i + rowH / 2;
        var x0 = Xv(0), x1 = Xv(r.value);
        var th = 12, rad = Math.min(4, Math.abs(x1 - x0));
        var s = r.value >= 0 ? 1 : -1;
        var d = 'M' + x0 + ',' + (cy - th / 2) + 'L' + (x1 - s * rad) + ',' + (cy - th / 2) + 'Q' + x1 + ',' + (cy - th / 2) + ' ' + x1 + ',' + (cy - th / 2 + rad) +
          'L' + x1 + ',' + (cy + th / 2 - rad) + 'Q' + x1 + ',' + (cy + th / 2) + ' ' + (x1 - s * rad) + ',' + (cy + th / 2) + 'L' + x0 + ',' + (cy + th / 2) + 'Z';
        var bar = S('path', { d: d, class: 'viz-fill ' + (o.sign === false ? (o.cls || 's1') : (r.value >= 0 ? 'up' : 'down')) });
        bindMark(bar, api, function () { return [{ value: fmt(r.value), label: o.valueLabel || '' }].concat(r.note ? [{ value: r.note, label: o.noteLabel || '' }] : []); }, r.label);
        add(svg, S('text', { x: nameW - 8, y: cy + 4, class: 'viz-tick', 'text-anchor': 'end' }, r.label), bar,
          S('text', { x: r.value >= 0 ? x1 + 6 : x1 - 6, y: cy + 4, class: 'viz-label', 'text-anchor': r.value >= 0 ? 'start' : 'end' }, fmt(r.value)));
      });
      return svg;
    });
  }

  /* 哑铃图：每行一个项目，两个点（之前 → 之后）。rows: [{label, a, b}]；names: [a 的名字, b 的名字] */
  function dumbbell(o) {
    var fmt = o.fmt || pctFmt(1);
    var rows = o.rows;
    return figure({ title: o.title, sub: o.sub, note: o.note, table: { head: [o.catLabel || ''].concat(o.names), rows: rows.map(function (r) { return [r.label, fmt(r.a), fmt(r.b)]; }) } }, function (W, api) {
      api.setLegend([{ name: o.names[0], cls: 'mute', shape: 'dot' }, { name: o.names[1], cls: 's1', shape: 'dot' }]);
      var rowH = 26, padT = 6, padB = 24, nameW = Math.min(150, Math.max(84, W * 0.26)), padR = 66;
      var Hh = padT + padB + rowH * rows.length;
      var vals = [];
      rows.forEach(function (r) { [r.a, r.b].forEach(function (v) { if (v !== null && v !== undefined && isFinite(v)) vals.push(v); }); });
      var lo = Math.min(0, Math.min.apply(null, vals)), hi = Math.max(0, Math.max.apply(null, vals));
      var ticks = niceTicks(lo, hi, 4);
      lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
      var pw = W - nameW - padR;
      var Xv = function (v) { return nameW + (v - lo) / (hi - lo || 1) * pw; };
      var svg = S('svg', { width: W, height: Hh, viewBox: '0 0 ' + W + ' ' + Hh, role: 'img', 'aria-label': (o.title || '对比图') + '。数值见下方「看数字」' });
      ticks.forEach(function (t) {
        add(svg, S('line', { x1: Xv(t), x2: Xv(t), y1: padT, y2: Hh - padB, class: t === 0 ? 'viz-axis' : 'viz-grid' }),
          S('text', { x: Xv(t), y: Hh - 8, class: 'viz-tick', 'text-anchor': 'middle' }, fmt(t)));
      });
      rows.forEach(function (r, i) {
        var cy = padT + rowH * i + rowH / 2;
        add(svg, S('text', { x: nameW - 8, y: cy + 4, class: 'viz-tick', 'text-anchor': 'end' }, r.label));
        var hasA = r.a !== null && r.a !== undefined && isFinite(r.a), hasB = r.b !== null && r.b !== undefined && isFinite(r.b);
        if (hasA && hasB) add(svg, S('line', { x1: Xv(r.a), x2: Xv(r.b), y1: cy, y2: cy, class: 'viz-link' }));
        var hit = S('rect', { x: nameW, y: cy - rowH / 2, width: pw + padR, height: rowH, class: 'viz-hit' });
        bindMark(hit, api, function () { return [{ cls: 'mute', value: fmt(r.a), label: o.names[0] }, { cls: 's1', value: fmt(r.b), label: o.names[1] }]; }, r.label);
        if (hasA) add(svg, S('circle', { cx: Xv(r.a), cy: cy, r: 5, class: 'viz-dot mute' }));
        if (hasB) add(svg, S('circle', { cx: Xv(r.b), cy: cy, r: 5, class: 'viz-dot s1' }),
          S('text', { x: Xv(Math.max(hasA ? r.a : r.b, r.b)) + 10, y: cy + 4, class: 'viz-label' }, fmt(r.b)));
        add(svg, hit);
      });
      return svg;
    });
  }

  /* 走势小图：一条线 + 末端一个点，可以带一两条参考线（比如止损价）。values: 收盘价；o.refs: [{y, label, cls}] */
  function spark(values, o) {
    o = o || {};
    var W = o.width || 220, Hh = o.height || 56, pad = 5;
    var vals = values.filter(function (v) { return v !== null && isFinite(v); });
    (o.refs || []).forEach(function (r) { vals.push(r.y); });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var n = values.length;
    var X = function (i) { return pad + (W - pad * 2 - 2) * i / Math.max(1, n - 1); };
    var Y = function (v) { return pad + (hi - v) / (hi - lo || 1) * (Hh - pad * 2); };
    var svg = S('svg', { width: W, height: Hh, viewBox: '0 0 ' + W + ' ' + Hh, class: 'viz-spark', role: 'img', 'aria-label': o.label || '走势' });
    (o.refs || []).forEach(function (r) {
      add(svg, S('line', { x1: pad, x2: W - pad, y1: Y(r.y), y2: Y(r.y), class: 'viz-ref ' + (r.cls || '') }));
      if (r.label) add(svg, S('text', { x: pad + 2, y: Y(r.y) - 3, class: 'viz-tick' }, r.label));
    });
    var d = '';
    values.forEach(function (v, i) { d += (i ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1); });
    add(svg, S('path', { d: d, class: 'viz-line thin ' + (o.cls || 'mute-line') }),
      S('circle', { cx: X(n - 1), cy: Y(values[n - 1]), r: 3.5, class: 'viz-dot ' + (o.dot || 's1') }));
    return svg;
  }

  window.TYViz = { columns: columns, lines: lines, meter: meter, meterList: meterList, hbars: hbars, dumbbell: dumbbell, spark: spark, pct: pctFmt };
})();
