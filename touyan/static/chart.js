/* 图表：K 线 / 净值图（主图 + 成交量或回撤 + 指标副图）与多序列对比折线图。纯 canvas，无依赖。
 *
 * 约定（遵循数据可视化规范）：
 * - 只有一个纵轴。与基准比较时两条线都按区间起点 = 100 归一，绝不做双纵轴；
 * - 十字光标对齐最近的交易日，悬停提示列出该日所有序列的数值；键盘 ←/→ 同样可用；
 * - 均线等多序列有图例（线形色块 + 数值），文字一律用文字色，颜色只在线条上；
 * - 涨跌除了红/绿，阳线空心、阴线实心——红绿色弱也能分清；
 * - 网格与坐标轴是实线细线，退在数据后面。
 */
(function () {
  'use strict';

  function dpr() { return Math.min(3, Math.max(1, window.devicePixelRatio || 1)); }

  function tokens() {
    var cs = getComputedStyle(document.documentElement);
    var v = function (n) { return cs.getPropertyValue(n).trim(); };
    return {
      surface: v('--surface'), grid: v('--grid'), axis: v('--axis'), muted: v('--muted'),
      text: v('--text'), text2: v('--text-2'), up: v('--up'), down: v('--down'),
      series: [v('--s1'), v('--s2'), v('--s3'), v('--s4'), v('--s5'), v('--s6')],
      font: v('--font') || 'sans-serif'
    };
  }

  function alpha(hex, a) {
    var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    if (!m) return hex;
    return 'rgba(' + parseInt(m[1], 16) + ',' + parseInt(m[2], 16) + ',' + parseInt(m[3], 16) + ',' + a + ')';
  }

  function niceTicks(min, max, count) {
    if (!(isFinite(min) && isFinite(max))) return [];
    if (max - min < 1e-12) { max = min + Math.abs(min || 1) * 0.01; min = min - Math.abs(min || 1) * 0.01; }
    var raw = (max - min) / Math.max(1, count);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    var step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    var out = [];
    for (var v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  function decimalsFor(range) {
    if (range >= 50) return 0;
    if (range >= 5) return 1;
    if (range >= 0.5) return 2;
    if (range >= 0.05) return 3;
    return 4;
  }

  function compact(v) {
    var a = Math.abs(v);
    if (a >= 1e8) return (v / 1e8).toFixed(a >= 1e9 ? 0 : 1) + '亿';
    if (a >= 1e4) return (v / 1e4).toFixed(a >= 1e5 ? 0 : 1) + '万';
    return String(Math.round(v));
  }

  function fmt(v, d) {
    if (v === null || v === undefined || !isFinite(v)) return '—';
    return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function pct(v, d) {
    if (v === null || v === undefined || !isFinite(v)) return '—';
    return (v >= 0 ? '+' : '') + v.toFixed(d === undefined ? 2 : d) + '%';
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ── 基类：画布、尺寸、指针与键盘、提示框 ──────────────────────
  function Base(host, opts) {
    var self = this;
    this.host = host;
    this.opts = opts || {};
    host.classList.add('chart-host');
    this.legend = el('div', 'chart-legend');
    this.canvas = el('canvas');
    this.canvas.tabIndex = 0;
    this.canvas.setAttribute('role', 'img');
    this.tip = el('div', 'chart-tip');
    this.tip.hidden = true;
    host.replaceChildren(this.legend, this.canvas, this.tip);
    this.hover = null;
    this.pointer = null;
    this._raf = 0;
    this._ro = new ResizeObserver(function () { self.schedule(); });
    this._ro.observe(host);
    this._mq = window.matchMedia('(prefers-color-scheme: dark)');
    this._onTheme = function () { self.schedule(); };
    this._mq.addEventListener('change', this._onTheme);
    this._mo = new MutationObserver(function () { self.schedule(); });
    this._mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-updown'] });
    this.canvas.addEventListener('pointermove', function (e) { self._point(e); });
    this.canvas.addEventListener('pointerdown', function (e) { self._point(e); });
    this.canvas.addEventListener('pointerleave', function (e) {
      if (e.pointerType === 'mouse') { self.pointer = null; self.setHover(null); }
    });
    this.canvas.addEventListener('keydown', function (e) { self._key(e); });
    this.canvas.addEventListener('blur', function () { self.setHover(null); });
  }
  Base.prototype.schedule = function () {
    var self = this;
    cancelAnimationFrame(this._raf);
    this._raf = requestAnimationFrame(function () { self.draw(); });
  };
  Base.prototype.prepare = function () {
    var w = Math.max(280, this.host.clientWidth);
    var h = this.height(w);
    var r = dpr();
    if (this.canvas.width !== Math.round(w * r) || this.canvas.height !== Math.round(h * r)) {
      this.canvas.width = Math.round(w * r);
      this.canvas.height = Math.round(h * r);
      this.canvas.style.height = h + 'px';
    }
    var ctx = this.canvas.getContext('2d');
    ctx.setTransform(r, 0, 0, r, 0, 0);
    ctx.clearRect(0, 0, w, h);
    this.w = w;
    this.h = h;
    this.t = tokens();
    ctx.font = '11px ' + this.t.font;
    return ctx;
  };
  Base.prototype.destroy = function () {
    cancelAnimationFrame(this._raf);
    this._ro.disconnect();
    this._mo.disconnect();
    this._mq.removeEventListener('change', this._onTheme);
  };
  Base.prototype._point = function (e) {
    var r = this.canvas.getBoundingClientRect();
    this.pointer = { x: e.clientX - r.left, y: e.clientY - r.top };
    this.setHover(this.indexAt(this.pointer.x));
  };
  Base.prototype._key = function (e) {
    var last = this.lastIndex();
    var first = this.firstIndex();
    var cur = this.hover === null ? last : this.hover;
    var next = cur;
    if (e.key === 'ArrowLeft') next = Math.max(first, cur - 1);
    else if (e.key === 'ArrowRight') next = Math.min(last, cur + 1);
    else if (e.key === 'Home') next = first;
    else if (e.key === 'End') next = last;
    else if (e.key === 'Escape') { this.setHover(null); return; }
    else return;
    e.preventDefault();
    this.pointer = null;
    this.setHover(next);
  };
  Base.prototype.setHover = function (i) {
    if (i === this.hover && this.pointer === null) return;
    this.hover = i;
    this.schedule();
  };
  Base.prototype.showTip = function (title, rows, x) {
    var tip = this.tip;
    tip.replaceChildren();
    tip.appendChild(el('div', 'tt', title));
    rows.forEach(function (r) {
      var row = el('div', 'tr');
      var name = el('span', '', '');
      if (r.color) { var key = el('i'); key.style.background = r.color; name.appendChild(key); }
      name.appendChild(document.createTextNode(r.label));
      var val = el('b', r.cls || '', r.value);
      row.appendChild(name);
      row.appendChild(val);
      tip.appendChild(row);
    });
    tip.hidden = false;
    var tw = tip.offsetWidth;
    var left = x + 14;
    if (left + tw > this.w - 4) left = x - tw - 14;
    tip.style.left = Math.max(4, left) + 'px';
    tip.style.top = (this.legend.offsetHeight + 8) + 'px';
  };
  Base.prototype.setLegend = function (items) {
    var lg = this.legend;
    lg.replaceChildren();
    items.forEach(function (it) {
      var k = el('span', 'key');
      if (it.color) { var i = el('i'); i.style.background = it.color; k.appendChild(i); }
      k.appendChild(document.createTextNode(it.label + ' '));
      k.appendChild(el('b', it.cls || '', it.value));
      lg.appendChild(k);
    });
  };

  function line(ctx, xs, ys, color, width) {
    ctx.beginPath();
    var started = false;
    for (var k = 0; k < xs.length; k++) {
      var y = ys[k];
      if (y === null || y === undefined || !isFinite(y)) { started = false; continue; }
      if (!started) { ctx.moveTo(xs[k], y); started = true; } else ctx.lineTo(xs[k], y);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
  }

  function hline(ctx, x0, x1, y, color) {
    ctx.beginPath();
    ctx.moveTo(x0, Math.round(y) + 0.5);
    ctx.lineTo(x1, Math.round(y) + 0.5);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  function dateLabels(dates, start, end, xOf, minGap) {
    var out = [];
    var span = end - start;
    var lastX = -1e9;
    for (var i = start; i < end; i++) {
      var d = dates[i];
      var prev = i > start ? dates[i - 1] : null;
      var mark = false;
      if (span <= 70) mark = !prev || d.slice(5, 7) !== prev.slice(5, 7) || (i - start) % 10 === 0;
      else if (span <= 300) mark = !prev || d.slice(5, 7) !== prev.slice(5, 7);
      else mark = !prev || (d.slice(5, 7) !== prev.slice(5, 7) && ['01', '04', '07', '10'].indexOf(d.slice(5, 7)) >= 0);
      if (!mark) continue;
      var x = xOf(i);
      if (x - lastX < minGap) continue;
      out.push({ x: x, text: span <= 70 ? d.slice(5) : d.slice(0, 7) });
      lastX = x;
    }
    return out;
  }

  // ── K 线 / 净值图 ─────────────────────────────────────────────
  function PriceChart(host, data, opts) {
    Base.call(this, host, opts);
    this.data = data;
    this.n = data.dates.length;
    this.state = {
      range: Math.min(opts.range || 120, this.n),
      overlay: 'ma',
      ind: opts.isNav ? 'none' : 'macd',
      mode: 'price'
    };
    var last = this.n - 1;
    this.canvas.setAttribute('aria-label', (opts.name || '') + (opts.isNav ? ' 净值走势图' : ' K 线图') +
      '，最新 ' + data.dates[last] + ' 收于 ' + fmt(data.close[last], opts.digits || 2) + '。可用左右方向键逐日查看。');
    this.schedule();
  }
  PriceChart.prototype = Object.create(Base.prototype);
  PriceChart.prototype.set = function (key, value) {
    this.state[key] = key === 'range' ? Math.min(value, this.n) : value;
    this.hover = null;
    this.schedule();
  };
  PriceChart.prototype.hasVolume = function () {
    return !this.opts.isNav && this.data.volume.some(function (v) { return v > 0; });
  };
  PriceChart.prototype.height = function (w) {
    // 与 draw() 的分区严格对应：主图 → 副图(66) → 指标(86) → 日期轴(22)
    var main = w < 560 ? 260 : 340;
    if (this.state.mode === 'relative') return main + 22;
    return main + (this.state.ind !== 'none' ? 194 : 98);
  };
  PriceChart.prototype.firstIndex = function () { return this.n - this.state.range; };
  PriceChart.prototype.lastIndex = function () { return this.n - 1; };
  PriceChart.prototype.indexAt = function (x) {
    if (!this.geo) return null;
    var g = this.geo;
    var i = Math.floor((x - g.left) / g.step) + g.start;
    return Math.max(g.start, Math.min(this.n - 1, i));
  };

  PriceChart.prototype.draw = function () {
    var ctx = this.prepare();
    var t = this.t, d = this.data, s = this.state, o = this.opts;
    var digits = o.digits || 2;
    var start = this.n - s.range, end = this.n;
    var axisW = 58, left = 6, right = this.w - axisW, plotW = right - left;
    var step = plotW / s.range;
    var xOf = function (i) { return left + (i - start + 0.5) * step; };
    var relative = s.mode === 'relative';
    var mainTop = 6, mainH = (this.w < 560 ? 260 : 340) - 10;
    var subTop = mainTop + mainH + 10, subH = relative ? 0 : 66;
    var indTop = subTop + subH + 10, indH = (!relative && s.ind !== 'none') ? 86 : 0;
    var axisY = relative ? mainTop + mainH + 4 : (indH ? indTop + indH + 4 : subTop + subH + 4);
    this.geo = { left: left, step: step, start: start };
    var panes = [];
    var xs = [];
    for (var i = start; i < end; i++) xs.push(xOf(i));
    var slice = function (arr) { return arr ? arr.slice(start, end) : []; };
    var hv = this.hover;
    var focus = hv === null ? end - 1 : hv;

    // ── 主图 ──
    var mainSeries = [];
    var lo = Infinity, hi = -Infinity;
    var consider = function (arr) { for (var k = start; k < end; k++) { var v = arr[k]; if (v !== null && v !== undefined && isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } } };
    var rel = null;
    if (relative) {
      var base = (d.adj || d.close);
      var b0 = base[start];
      var mine = base.map(function (v) { return v / b0 * 100; });
      var bench = null;
      if (d.benchmark) {
        var bb = null;
        for (var k = start; k < end; k++) { if (d.benchmark[k] !== null) { bb = d.benchmark[k]; break; } }
        if (bb) bench = d.benchmark.map(function (v) { return v === null ? null : v / bb * 100; });
      }
      rel = { mine: mine, bench: bench };
      consider(mine);
      if (bench) consider(bench);
    } else {
      if (o.isNav) consider(d.close); else { consider(d.low); consider(d.high); }
      if (s.overlay === 'ma') {
        (o.isNav ? ['ma20', 'ma60'] : ['ma5', 'ma20', 'ma60']).forEach(function (k2, idx) {
          mainSeries.push({ key: k2, label: k2.toUpperCase(), color: t.series[o.isNav ? idx + 1 : idx], values: d[k2] });
          consider(d[k2]);
        });
      } else if (s.overlay === 'boll') {
        [['boll_up', '上轨'], ['boll_mid', '中轨'], ['boll_low', '下轨']].forEach(function (p, idx) {
          mainSeries.push({ key: p[0], label: 'BOLL ' + p[1], color: idx === 1 ? t.series[1] : t.series[0], values: d[p[0]] });
          consider(d[p[0]]);
        });
      }
    }
    var pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.02 || 1;
    lo -= pad; hi += pad;
    var yMain = function (v) { return mainTop + (hi - v) / (hi - lo) * mainH; };
    panes.push({ top: mainTop, h: mainH, y: yMain, lo: lo, hi: hi, key: 'main' });
    var ticks = niceTicks(lo, hi, this.w < 560 ? 4 : 6);
    var tdec = relative ? 0 : decimalsFor((hi - lo) / 5);
    ctx.textBaseline = 'middle';
    ticks.forEach(function (v) {
      var y = yMain(v);
      if (y < mainTop + 4 || y > mainTop + mainH - 4) return;
      hline(ctx, left, right, y, t.grid);
      ctx.fillStyle = t.muted;
      ctx.fillText(relative ? pct(v - 100, 0) : fmt(v, tdec), right + 6, y);
    });

    if (relative) {
      hline(ctx, left, right, yMain(100), t.axis);
      if (rel.bench) line(ctx, xs, slice(rel.bench).map(yMain), t.muted, 1.5);
      line(ctx, xs, slice(rel.mine).map(yMain), t.series[0], 2);
      var dotAt = function (arr, color) {
        var y = yMain(arr[end - 1]);
        if (!isFinite(y)) return;
        ctx.beginPath(); ctx.arc(xs[xs.length - 1], y, 4, 0, Math.PI * 2);
        ctx.fillStyle = color; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = t.surface; ctx.stroke();
      };
      if (rel.bench && rel.bench[end - 1] !== null) dotAt(rel.bench, t.muted);
      dotAt(rel.mine, t.series[0]);
    } else if (o.isNav) {
      var navY = slice(d.close).map(yMain);
      ctx.beginPath();
      ctx.moveTo(xs[0], mainTop + mainH);
      for (var q = 0; q < xs.length; q++) ctx.lineTo(xs[q], navY[q]);
      ctx.lineTo(xs[xs.length - 1], mainTop + mainH);
      ctx.closePath();
      ctx.fillStyle = alpha(t.series[0], 0.08);
      ctx.fill();
      line(ctx, xs, navY, t.series[0], 2);
    } else {
      var bw = Math.max(1, Math.min(step * 0.68, 14));
      for (var j = start; j < end; j++) {
        var op = d.open[j], cl = d.close[j], hh = d.high[j], ll = d.low[j];
        var up = cl >= op;
        var color = up ? t.up : t.down;
        var x = Math.round(xOf(j)) + 0.5;
        var yo = yMain(op), yc = yMain(cl), yh = yMain(hh), yl = yMain(ll);
        var top = Math.min(yo, yc), bot = Math.max(yo, yc);
        if (bot - top < 1) bot = top + 1;
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1;
        var hollow = up && bw >= 4;
        ctx.beginPath();
        if (hollow) {
          ctx.moveTo(x, yh); ctx.lineTo(x, top);
          ctx.moveTo(x, bot); ctx.lineTo(x, yl);
        } else {
          ctx.moveTo(x, yh); ctx.lineTo(x, yl);
        }
        ctx.stroke();
        var bx = Math.round(xOf(j) - bw / 2);
        if (hollow) ctx.strokeRect(bx + 0.5, Math.round(top) + 0.5, Math.round(bw) - 1, Math.max(1, Math.round(bot - top) - 1));
        else ctx.fillRect(bx, Math.round(top), Math.max(1, Math.round(bw)), Math.max(1, Math.round(bot - top)));
      }
    }
    if (s.overlay === 'boll' && !relative) {
      var upY = slice(d.boll_up).map(yMain), lowY = slice(d.boll_low).map(yMain);
      ctx.beginPath();
      var began = false;
      for (var a = 0; a < xs.length; a++) { if (!isFinite(upY[a])) continue; if (!began) { ctx.moveTo(xs[a], upY[a]); began = true; } else ctx.lineTo(xs[a], upY[a]); }
      for (var b = xs.length - 1; b >= 0; b--) { if (isFinite(lowY[b])) ctx.lineTo(xs[b], lowY[b]); }
      ctx.closePath();
      ctx.fillStyle = alpha(t.series[0], 0.06);
      ctx.fill();
    }
    mainSeries.forEach(function (ms) { line(ctx, xs, slice(ms.values).map(yMain), ms.color, 1.5); });

    // ── 副图：成交量 / 回撤 ──
    if (!relative) {
      var sub = { top: subTop, h: subH, key: 'sub' };
      if (this.hasVolume()) {
        var vmax = Math.max.apply(null, slice(d.volume)) || 1;
        sub.y = function (v) { return subTop + subH - v / vmax * subH; };
        sub.lo = 0; sub.hi = vmax;
        var vw = Math.max(1, Math.min(step * 0.68, 14));
        for (var m = start; m < end; m++) {
          var upv = d.close[m] >= d.open[m];
          ctx.fillStyle = alpha(upv ? t.up : t.down, 0.55);
          var vy = sub.y(d.volume[m]);
          ctx.fillRect(Math.round(xOf(m) - vw / 2), Math.round(vy), Math.max(1, Math.round(vw)), Math.max(0, Math.round(subTop + subH - vy)));
        }
        hline(ctx, left, right, subTop + subH, t.axis);
        ctx.fillStyle = t.muted;
        ctx.fillText(compact(vmax), right + 6, subTop + 6);
        ctx.fillText('成交量', right + 6, subTop + subH - 8);
        sub.fmt = function (v) { return compact(v) + (o.volumeUnit || ''); };
      } else {
        var dd = slice(d.drawdown);
        var dmin = Math.min.apply(null, dd.filter(function (v) { return v !== null; }).concat([-0.01]));
        sub.y = function (v) { return subTop + (0 - v) / (0 - dmin) * subH; };
        sub.lo = dmin; sub.hi = 0;
        ctx.beginPath();
        ctx.moveTo(xs[0], subTop);
        for (var p = 0; p < xs.length; p++) ctx.lineTo(xs[p], sub.y(dd[p] || 0));
        ctx.lineTo(xs[xs.length - 1], subTop);
        ctx.closePath();
        ctx.fillStyle = alpha(t.text2, 0.12);
        ctx.fill();
        line(ctx, xs, dd.map(function (v) { return sub.y(v || 0); }), t.text2, 1.5);
        hline(ctx, left, right, subTop, t.axis);
        ctx.fillStyle = t.muted;
        ctx.fillText('回撤', right + 6, subTop + 6);
        ctx.fillText(pct(dmin * 100, 0), right + 6, subTop + subH - 6);
        sub.fmt = function (v) { return pct(v * 100, 1); };
      }
      panes.push(sub);
    }

    // ── 指标副图 ──
    var indSeries = [];
    if (indH) {
      var ip = { top: indTop, h: indH, key: 'ind' };
      var ilo, ihi, refs = [];
      if (s.ind === 'macd') {
        var vals = slice(d.dif).concat(slice(d.dea), slice(d.macd)).filter(function (v) { return v !== null; });
        var amax = Math.max.apply(null, vals.map(Math.abs).concat([1e-9]));
        ilo = -amax * 1.1; ihi = amax * 1.1; refs = [0];
        indSeries = [{ label: 'DIF', color: t.series[0], values: d.dif }, { label: 'DEA', color: t.series[1], values: d.dea }];
      } else if (s.ind === 'rsi') {
        ilo = 0; ihi = 100; refs = [30, 70];
        indSeries = [{ label: 'RSI14', color: t.series[0], values: d.rsi14 }, { label: 'RSI6', color: t.series[1], values: d.rsi6 }];
      } else {
        var kv = slice(d.j).filter(function (v) { return v !== null; });
        ilo = Math.min(0, Math.min.apply(null, kv.concat([0]))); ihi = Math.max(100, Math.max.apply(null, kv.concat([100]))); refs = [20, 80];
        indSeries = [{ label: 'K', color: t.series[0], values: d.k }, { label: 'D', color: t.series[1], values: d.d }, { label: 'J', color: t.series[2], values: d.j }];
      }
      ip.y = function (v) { return indTop + (ihi - v) / (ihi - ilo) * indH; };
      ip.lo = ilo; ip.hi = ihi;
      refs.forEach(function (r) {
        hline(ctx, left, right, ip.y(r), r === 0 ? t.axis : t.grid);
        ctx.fillStyle = t.muted;
        ctx.fillText(String(r), right + 6, ip.y(r));
      });
      if (s.ind === 'macd') {
        var hw = Math.max(1, Math.min(step * 0.5, 8));
        for (var z = start; z < end; z++) {
          var hvv = d.macd[z];
          if (hvv === null) continue;
          ctx.fillStyle = alpha(hvv >= 0 ? t.up : t.down, 0.7);
          var y0 = ip.y(0), y1 = ip.y(hvv);
          ctx.fillRect(Math.round(xOf(z) - hw / 2), Math.round(Math.min(y0, y1)), Math.max(1, Math.round(hw)), Math.max(1, Math.round(Math.abs(y1 - y0))));
        }
        ctx.fillStyle = t.muted;
        ctx.fillText('MACD', right + 6, indTop + 6);
      }
      indSeries.forEach(function (sr) { line(ctx, xs, slice(sr.values).map(ip.y), sr.color, 1.5); });
      ip.fmt = function (v) { return fmt(v, s.ind === 'macd' ? 3 : 1); };
      panes.push(ip);
    }

    // ── 横轴日期 ──
    ctx.fillStyle = t.muted;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'center';
    dateLabels(d.dates, start, end, xOf, this.w < 560 ? 64 : 76).forEach(function (lb) {
      if (lb.x < left + 20 || lb.x > right - 20) return;
      ctx.fillText(lb.text, lb.x, axisY + 2);
    });
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';

    // ── 十字光标 ──
    if (hv !== null && hv >= start) {
      var cx = Math.round(xOf(hv)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(cx, mainTop);
      ctx.lineTo(cx, axisY);
      ctx.strokeStyle = t.text2;
      ctx.lineWidth = 1;
      ctx.stroke();
      if (this.pointer) {
        var py = this.pointer.y;
        var pane = panes.filter(function (pn) { return py >= pn.top && py <= pn.top + pn.h; })[0];
        if (pane && pane.y) {
          hline(ctx, left, right, py, alpha(t.text2, 0.6));
          var val = pane.lo + (pane.hi - pane.lo) * (pane.key === 'main' ? (mainTop + mainH - py) / mainH : (pane.top + pane.h - py) / pane.h);
          var text = pane.key === 'main' ? (relative ? pct(val - 100, 1) : fmt(val, digits)) : (pane.fmt ? pane.fmt(val) : fmt(val, 2));
          var tw = ctx.measureText(text).width + 10;
          ctx.fillStyle = t.text;
          ctx.fillRect(right + 2, py - 9, tw, 18);
          ctx.fillStyle = t.surface;
          ctx.fillText(text, right + 7, py);
        }
      }
      ctx.fillStyle = t.text;
      var dl = d.dates[hv];
      var dw = ctx.measureText(dl).width + 12;
      var dx = Math.max(left, Math.min(right - dw, cx - dw / 2));
      ctx.fillRect(dx, axisY, dw, 18);
      ctx.fillStyle = t.surface;
      ctx.textBaseline = 'top';
      ctx.fillText(dl, dx + 6, axisY + 3);
      ctx.textBaseline = 'middle';
    }

    // ── 图例与提示 ──
    var legend = [];
    if (relative) {
      legend.push({ label: o.name || '本品种', color: t.series[0], value: pct(rel.mine[focus] - 100), cls: rel.mine[focus] >= 100 ? 'up' : 'down' });
      if (rel.bench) legend.push({ label: o.benchName || '基准', color: t.muted, value: rel.bench[focus] === null ? '—' : pct(rel.bench[focus] - 100), cls: rel.bench[focus] >= 100 ? 'up' : 'down' });
    } else {
      mainSeries.forEach(function (ms) { legend.push({ label: ms.label, color: ms.color, value: fmt(ms.values[focus], digits) }); });
      indSeries.forEach(function (sr) { legend.push({ label: sr.label, color: sr.color, value: fmt(sr.values[focus], s.ind === 'macd' ? 3 : 1) }); });
      if (s.ind === 'macd' && d.macd[focus] !== null) legend.push({ label: 'MACD柱', value: fmt(d.macd[focus], 3), cls: d.macd[focus] >= 0 ? 'up' : 'down' });
    }
    this.setLegend(legend);

    if (hv === null || hv < start) { this.tip.hidden = true; return; }
    var prev = hv > 0 ? d.close[hv - 1] : null;
    var chg = prev ? (d.close[hv] / prev - 1) * 100 : null;
    var rows = [];
    if (relative) {
      rows.push({ label: o.name || '本品种', color: t.series[0], value: pct(rel.mine[hv] - 100) });
      if (rel.bench && rel.bench[hv] !== null) {
        rows.push({ label: o.benchName || '基准', color: t.muted, value: pct(rel.bench[hv] - 100) });
        var ex = rel.mine[hv] - rel.bench[hv];
        rows.push({ label: '相对超额', value: pct(ex), cls: ex >= 0 ? 'up' : 'down' });
      }
    } else if (o.isNav) {
      rows.push({ label: '单位净值', value: fmt(d.close[hv], digits) });
      rows.push({ label: '日涨跌', value: pct(chg), cls: chg >= 0 ? 'up' : 'down' });
      if (d.drawdown[hv] !== null) rows.push({ label: '距高点回撤', value: pct(d.drawdown[hv] * 100) });
    } else {
      rows.push({ label: '开盘', value: fmt(d.open[hv], digits) });
      rows.push({ label: '最高', value: fmt(d.high[hv], digits) });
      rows.push({ label: '最低', value: fmt(d.low[hv], digits) });
      rows.push({ label: '收盘', value: fmt(d.close[hv], digits) });
      rows.push({ label: '涨跌幅', value: pct(chg), cls: chg >= 0 ? 'up' : 'down' });
      if (this.hasVolume()) rows.push({ label: '成交量', value: compact(d.volume[hv]) + (o.volumeUnit || '') });
    }
    this.showTip(d.dates[hv], rows, xOf(hv));
  };

  // ── 多序列对比折线（统一按起点 = 100 归一） ─────────────────
  function LineChart(host, data, opts) {
    Base.call(this, host, opts);
    this.data = data;
    this.n = data.dates.length;
    this.canvas.setAttribute('aria-label', '对比走势图：' + data.series.map(function (s) { return s.name; }).join('、') + '。可用左右方向键逐日查看。');
    this.schedule();
  }
  LineChart.prototype = Object.create(Base.prototype);
  LineChart.prototype.height = function (w) { return (w < 560 ? 260 : 340) + 26; };
  LineChart.prototype.firstIndex = function () { return 0; };
  LineChart.prototype.lastIndex = function () { return this.n - 1; };
  LineChart.prototype.indexAt = function (x) {
    if (!this.geo) return null;
    var i = Math.round((x - this.geo.left) / this.geo.step);
    return Math.max(0, Math.min(this.n - 1, i));
  };
  LineChart.prototype.draw = function () {
    var ctx = this.prepare();
    var t = this.t, d = this.data;
    var axisW = 58, left = 8, right = this.w - axisW, top = 8, plotH = this.h - 26 - top - 6;
    var step = this.n > 1 ? (right - left) / (this.n - 1) : 1;
    this.geo = { left: left, step: step };
    var xOf = function (i) { return left + i * step; };
    var lo = Infinity, hi = -Infinity;
    d.series.forEach(function (s) { s.values.forEach(function (v) { if (v !== null) { if (v < lo) lo = v; if (v > hi) hi = v; } }); });
    if (!isFinite(lo)) return;
    var pad = (hi - lo) * 0.06 || 1;
    lo -= pad; hi += pad;
    var y = function (v) { return top + (hi - v) / (hi - lo) * plotH; };
    ctx.textBaseline = 'middle';
    niceTicks(lo, hi, this.w < 560 ? 4 : 6).forEach(function (v) {
      var yy = y(v);
      if (yy < top + 4 || yy > top + plotH - 4) return;
      hline(ctx, left, right, yy, Math.abs(v - 100) < 1e-9 ? t.axis : t.grid);
      ctx.fillStyle = t.muted;
      ctx.fillText(pct(v - 100, 0), right + 6, yy);
    });
    var xs = d.dates.map(function (_, i) { return xOf(i); });
    var colors = d.series.map(function (s, i) { return s.color || t.series[i % t.series.length]; });
    d.series.forEach(function (s, i) { line(ctx, xs, s.values.map(y), colors[i], 2); });
    d.series.forEach(function (s, i) {
      for (var k = s.values.length - 1; k >= 0; k--) {
        if (s.values[k] === null) continue;
        ctx.beginPath(); ctx.arc(xs[k], y(s.values[k]), 4, 0, Math.PI * 2);
        ctx.fillStyle = colors[i]; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = t.surface; ctx.stroke();
        break;
      }
    });
    ctx.fillStyle = t.muted;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'center';
    var axisY = top + plotH + 6;
    dateLabels(d.dates, 0, this.n, xOf, this.w < 560 ? 64 : 76).forEach(function (lb) {
      if (lb.x < left + 20 || lb.x > right - 20) return;
      ctx.fillText(lb.text, lb.x, axisY);
    });
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    var hv = this.hover;
    var focus = hv === null ? this.n - 1 : hv;
    var at = function (s) {
      for (var k = focus; k >= 0; k--) if (s.values[k] !== null) return s.values[k];
      return null;
    };
    this.setLegend(d.series.map(function (s, i) {
      var v = at(s);
      return { label: s.name, color: colors[i], value: v === null ? '—' : pct(v - 100), cls: v === null ? '' : v >= 100 ? 'up' : 'down' };
    }));
    if (hv === null) { this.tip.hidden = true; return; }
    var cx = Math.round(xOf(hv)) + 0.5;
    ctx.beginPath(); ctx.moveTo(cx, top); ctx.lineTo(cx, top + plotH); ctx.strokeStyle = t.text2; ctx.lineWidth = 1; ctx.stroke();
    var rows = d.series.map(function (s, i) { return { s: s, i: i, v: at(s) }; })
      .sort(function (a, b) { return (b.v === null ? -1e9 : b.v) - (a.v === null ? -1e9 : a.v); })
      .map(function (r) { return { label: r.s.name, color: colors[r.i], value: r.v === null ? '—' : pct(r.v - 100), cls: r.v === null ? '' : r.v >= 100 ? 'up' : 'down' }; });
    this.showTip(d.dates[hv], rows, xOf(hv));
  };

  window.TYChart = { PriceChart: PriceChart, LineChart: LineChart, fmt: fmt, pct: pct, compact: compact };
})();
