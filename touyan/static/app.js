/* 投研智能体 —— 前端（免构建，原生 JS）
 *
 * 路由（hash）：
 *   #/                首页搜索
 *   #/a/SH:600519     分析页（量化分析 + AI 深度分析）
 *   #/q/茅台          按名称/代码搜索后进入分析页
 *   #/csv/<id>        导入数据的分析页
 *   #/compare  #/history  #/report/<id>  #/settings  #/import
 *
 * 安全：所有来自数据源和大模型的文字都用 textContent 插入；只有经过 MD.render（先整体转义）
 * 的 Markdown 才用 innerHTML。
 */
(function () {
  'use strict';

  // ── 小工具 ───────────────────────────────────────────────────
  var $ = function (sel, root) { return (root || document).querySelector(sel); };

  function h(tag, attrs) {
    var e = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') e.className = v;
        else if (k === 'html') e.innerHTML = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
        else if (k === 'dataset') Object.assign(e.dataset, v);
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') e.addEventListener(k.slice(2), v);
        else if (v === true) e.setAttribute(k, '');
        else e.setAttribute(k, v);
      });
    }
    for (var i = 2; i < arguments.length; i++) append(e, arguments[i]);
    return e;
  }
  // replaceChildren 会把 null 和数组转成字符串，统一用 fill
  function fill(el) {
    el.replaceChildren();
    for (var i = 1; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(parent, kid) {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { append(parent, k); }); return; }
    parent.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }

  var LS = {
    get: function (k, d) { try { var v = localStorage.getItem('ty.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem('ty.' + k, JSON.stringify(v)); } catch (e) { /* 隐私模式等 */ } }
  };

  var F = {
    num: function (v, d) {
      if (v === null || v === undefined || !isFinite(v)) return '—';
      return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d === undefined ? 2 : d, maximumFractionDigits: d === undefined ? 2 : d });
    },
    pct: function (frac, d, signed) {
      if (frac === null || frac === undefined || !isFinite(frac)) return '—';
      var v = frac * 100;
      return (signed === false ? '' : v > 0 ? '+' : '') + v.toFixed(d === undefined ? 2 : d) + '%';
    },
    pp: function (v, d) {
      if (v === null || v === undefined || !isFinite(v)) return '—';
      return (v > 0 ? '+' : '') + Number(v).toFixed(d === undefined ? 2 : d) + '%';
    },
    money: function (v) {
      if (v === null || v === undefined || !isFinite(v)) return '—';
      var a = Math.abs(v);
      if (a >= 1e12) return (v / 1e12).toFixed(2) + ' 万亿';
      if (a >= 1e8) return (v / 1e8).toFixed(2) + ' 亿';
      if (a >= 1e4) return (v / 1e4).toFixed(2) + ' 万';
      return v.toFixed(2);
    },
    cls: function (v) { return v === null || v === undefined || !isFinite(v) || v === 0 ? 'flat' : v > 0 ? 'up' : 'down'; },
    digits: function (r) { var p = r.price.last || 0; return r.is_nav ? 4 : p < 1 ? 3 : 2; }
  };

  function toast(msg, kind) {
    var t = h('div', { class: 'toast' + (kind === 'err' ? ' err' : '') }, msg);
    $('#toasts').appendChild(t);
    setTimeout(function () { t.remove(); }, kind === 'err' ? 6000 : 3200);
  }

  function api(path, opts) {
    opts = opts || {};
    var url = path;
    if (opts.params) {
      var qs = new URLSearchParams();
      Object.keys(opts.params).forEach(function (k) {
        var v = opts.params[k];
        if (v !== undefined && v !== null && v !== '') qs.append(k, v);
      });
      var s = qs.toString();
      if (s) url += '?' + s;
    }
    var init = { method: opts.method || 'GET', headers: {} };
    if (opts.body instanceof FormData) init.body = opts.body;
    else if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
    return fetch(url, init).catch(function () {
      throw new Error('网络连接失败，请确认服务仍在运行');
    }).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!res.ok) {
          var msg = data && (data.error || data.detail);
          if (Array.isArray(msg)) msg = '参数有误：' + msg.map(function (d) { return d.msg; }).join('；');
          throw new Error(typeof msg === 'string' ? msg : '请求失败（HTTP ' + res.status + '）');
        }
        return data;
      });
    });
  }

  var state = { config: null, csvReports: {}, cleanup: [] };
  function onCleanup(fn) { state.cleanup.push(fn); }

  function loadConfig() {
    return api('/api/config').then(function (c) { state.config = c; return c; }).catch(function () { return state.config; });
  }

  // ── 主题 ─────────────────────────────────────────────────────
  function applyTheme() {
    var root = document.documentElement;
    var t = LS.get('theme', 'auto');
    if (t === 'light' || t === 'dark') root.dataset.theme = t; else delete root.dataset.theme;
    root.dataset.updown = LS.get('updown', 'red-up');
  }
  function effectiveDark() {
    var t = LS.get('theme', 'auto');
    if (t === 'dark') return true;
    if (t === 'light') return false;
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  // ── 路由 ─────────────────────────────────────────────────────
  function route() {
    state.cleanup.forEach(function (fn) { try { fn(); } catch (e) { /* ignore */ } });
    state.cleanup = [];
    var hash = location.hash || '#/';
    var m;
    var navKey = 'home';
    if (/^#\/compare/.test(hash)) navKey = 'compare';
    else if (/^#\/(history|report)/.test(hash)) navKey = 'history';
    else if (/^#\/settings/.test(hash)) navKey = 'settings';
    else if (/^#\/import/.test(hash)) navKey = 'import';
    else if (/^#\/daily/.test(hash)) navKey = 'daily';
    document.querySelectorAll('.nav a').forEach(function (a) { a.classList.toggle('active', a.dataset.nav === navKey); });
    window.scrollTo(0, 0);
    if ((m = hash.match(/^#\/a\/([^?]+)(?:\?(.*))?$/))) return viewAnalysis({ key: decodeURIComponent(m[1]), params: new URLSearchParams(m[2] || '') });
    if ((m = hash.match(/^#\/q\/([^?]+)(?:\?(.*))?$/))) return viewAnalysis({ q: decodeURIComponent(m[1]), params: new URLSearchParams(m[2] || '') });
    if ((m = hash.match(/^#\/csv\/(\w+)/))) return viewAnalysis({ csvId: m[1], params: new URLSearchParams() });
    if (navKey === 'compare') return viewCompare();
    if ((m = hash.match(/^#\/report\/(\w+)/))) return viewReport(m[1]);
    if (navKey === 'history') return viewHistory();
    if (navKey === 'settings') return viewSettings();
    if (navKey === 'import') return viewImport();
    if ((m = hash.match(/^#\/daily\/(\w+)/))) return viewDaily(m[1]);
    if (navKey === 'daily') return viewDaily(null, new URLSearchParams(hash.split('?')[1] || '').get('strategy') || undefined);
    return viewHome();
  }

  function view() { return $('#view'); }
  function setView() {
    var v = view();
    v.replaceChildren();
    for (var i = 0; i < arguments.length; i++) append(v, arguments[i]);
  }
  function loading(text) { return h('div', { class: 'loading' }, h('span', { class: 'spinner' }), text || '加载中……'); }
  function card(title, sub) {
    var c = h('section', { class: 'card' });
    if (title) c.appendChild(h('div', { class: 'card-head' }, h('h2', { class: 'card-title' }, title), sub ? h('span', { class: 'card-sub' }, sub) : null));
    for (var i = 2; i < arguments.length; i++) append(c, arguments[i]);
    return c;
  }
  function seg(options, current, onPick) {
    var wrap = h('div', { class: 'seg', role: 'group' });
    options.forEach(function (o) {
      var b = h('button', { type: 'button', class: o[0] === current ? 'on' : '', 'aria-pressed': o[0] === current ? 'true' : 'false' }, o[1]);
      b.addEventListener('click', function () {
        wrap.querySelectorAll('button').forEach(function (x) { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); });
        b.classList.add('on'); b.setAttribute('aria-pressed', 'true');
        onPick(o[0]);
      });
      wrap.appendChild(b);
    });
    return wrap;
  }
  function goInstrument(inst) {
    location.hash = '#/a/' + encodeURIComponent(inst.key) + (inst.kind ? '?kind=' + inst.kind : '');
  }

  // ── 搜索框 ───────────────────────────────────────────────────
  function searchBox(opts) {
    opts = opts || {};
    var input = h('input', { type: 'search', autocomplete: 'off', spellcheck: 'false', 'aria-label': '搜索证券或基金',
      placeholder: opts.placeholder || '代码或名称：600519、茅台、00700、AAPL、510300、110011' });
    var kind = h('select', { 'aria-label': '品种类型', title: '代码有歧义时指定品种（如 000001 既是平安银行也是上证指数）' },
      h('option', { value: 'auto' }, '自动'), h('option', { value: 'stock' }, '股票'), h('option', { value: 'etf' }, '场内基金'),
      h('option', { value: 'fund' }, '场外基金'), h('option', { value: 'index' }, '指数'));
    var btn = h('button', { class: 'btn btn-primary', type: 'button' }, opts.button || '分析');
    var list = h('div', { class: 'suggest', role: 'listbox', hidden: true });
    var items = [], active = -1, timer = 0, seq = 0;

    function hide() { list.hidden = true; }
    function render() {
      list.replaceChildren();
      items.forEach(function (it, i) {
        list.appendChild(h('button', { type: 'button', role: 'option', class: i === active ? 'active' : '',
          onmousedown: function (e) { e.preventDefault(); pick(it); } },
          h('span', { class: 'code' }, it.code), h('span', { class: 'nm' }, it.name || '（名称以行情为准）'),
          h('span', { class: 'badge' }, it.market_label + ' · ' + it.kind_label)));
      });
      list.hidden = !items.length;
    }
    function query() {
      var q = input.value.trim();
      if (!q) { items = []; hide(); return; }
      var my = ++seq;
      api('/api/search', { params: { q: q } }).then(function (r) {
        if (my !== seq) return;
        items = r.items || [];
        active = items.length ? 0 : -1;
        render();
      }).catch(function () { /* 搜索失败不打扰用户 */ });
    }
    function pick(it) {
      hide();
      input.value = '';
      if (opts.onPick) opts.onPick(it); else goInstrument(it);
    }
    function submit() {
      if (!list.hidden && items[active]) return pick(items[active]);
      var q = input.value.trim();
      if (!q) { input.focus(); return; }
      hide();
      if (opts.onPick) {
        api('/api/search', { params: { q: q } }).then(function (r) {
          var hit = (r.items || []).filter(function (x) { return kind.value === 'auto' || x.kind === kind.value; })[0];
          if (hit) pick(hit); else toast('找不到「' + q + '」', 'err');
        }).catch(function (e) { toast(e.message, 'err'); });
      } else {
        location.hash = '#/q/' + encodeURIComponent(q) + (kind.value !== 'auto' ? '?kind=' + kind.value : '');
      }
    }
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(query, 220); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' && items.length) { e.preventDefault(); active = (active + 1) % items.length; render(); }
      else if (e.key === 'ArrowUp' && items.length) { e.preventDefault(); active = (active - 1 + items.length) % items.length; render(); }
      else if (e.key === 'Enter') { e.preventDefault(); submit(); }
      else if (e.key === 'Escape') hide();
    });
    input.addEventListener('blur', function () { setTimeout(hide, 150); });
    btn.addEventListener('click', submit);
    if (opts.autofocus) setTimeout(function () { input.focus(); }, 30);
    return h('div', { class: 'search' }, h('div', { class: 'search-box' }, input, kind, btn), list);
  }

  // ── 首页 ─────────────────────────────────────────────────────
  var EXAMPLES = [
    { label: '贵州茅台', key: 'SH:600519' }, { label: '宁德时代', key: 'SZ:300750' },
    { label: '腾讯控股', key: 'HK:00700' }, { label: '苹果 AAPL', key: 'US:AAPL' },
    { label: '沪深300ETF', key: 'SH:510300' }, { label: '易方达蓝筹精选', key: 'OF:005827' },
    { label: '沪深300 指数', key: 'SH:000300' }
  ];

  function addRecent(inst) {
    var list = LS.get('recent', []).filter(function (x) { return x.key !== inst.key; });
    list.unshift({ key: inst.key, name: inst.name || inst.code, kind_label: inst.kind_label, kind: inst.kind });
    LS.set('recent', list.slice(0, 12));
  }

  function viewHome() {
    var c = state.config;
    var status = null;
    if (c && !c.llm_ready) {
      status = h('div', { class: 'notice-box warn', style: { maxWidth: '640px', margin: '18px auto 0' } },
        '量化分析可以直接使用；AI 深度分析需要先配置大模型（', c.llm_reason || '未配置', '）。',
        h('a', { href: '#/settings' }, '去设置 →'));
    }
    var recent = LS.get('recent', []);
    var running = (c && c.running_jobs) || [];
    setView(
      h('section', { class: 'hero' },
        h('h1', null, '股票 · 基金 · ETF 智能投研'),
        h('p', null, '输入代码或名称，几秒钟得到一份量化体检；需要深入研究时，让技术面、基本面、资讯分析师与多空研究员、交易员、风控团队协作辩论出结论。'),
        searchBox({ autofocus: true }),
        h('div', { class: 'chips' }, EXAMPLES.map(function (ex) {
          return h('button', { class: 'chip', type: 'button', onclick: function () { location.hash = '#/a/' + encodeURIComponent(ex.key); } }, ex.label);
        })),
        status),
      running.length ? card('正在进行的 AI 深度分析', null, h('div', { class: 'row' }, running.map(function (j) {
        return h('a', { class: 'chip', href: '#/a/' + encodeURIComponent(j.inst_key) + '?tab=ai' }, '● ' + j.title);
      }))) : null,
      recent.length ? card('最近查看', null, h('div', { class: 'row' }, recent.map(function (r) {
        return h('a', { class: 'chip', href: '#/a/' + encodeURIComponent(r.key) }, r.name + ' · ' + r.kind_label);
      }))) : null,
      h('div', { class: 'features' },
        feature('量化体检', '趋势、动量、风险、估值、质量、成长六个维度打分，每一分都列出依据。秒出、免费、不用大模型。'),
        feature('AI 多智能体研究', '移植 TradingAgents 的投研团队：分析师并行撰写报告，多空辩论，交易员给方案，风控审议，投资经理拍板。'),
        feature('基金分析', '场外基金与 ETF：复权净值收益、回撤、夏普、同类排名、基金经理任期、规模与清盘风险、重仓股。'),
        feature('复盘', '每次 AI 结论都会存档，之后自动对照实际走势计算收益与超额，看它到底准不准。'))
    );
  }
  function feature(title, text) { return h('div', { class: 'card feature' }, h('h3', null, title), h('p', null, text)); }

  // ── 分析页 ───────────────────────────────────────────────────
  function errorCard(msg, retry) {
    return card('没有拿到数据', null,
      h('div', { class: 'notice-box err' }, msg),
      h('p', { class: 't2 small' }, '常见原因：代码输入有误或品种类型不对（可在搜索框右侧指定「股票 / 场内基金 / 场外基金 / 指数」）；网络无法访问行情数据源；东方财富临时限流（几分钟后自动恢复，期间会改用腾讯等备用源）。'),
      h('div', { class: 'row' },
        retry ? h('button', { class: 'btn btn-primary', type: 'button', onclick: retry }, '重试') : null,
        h('a', { class: 'btn', href: '#/settings' }, '数据源自检'),
        h('a', { class: 'btn', href: '#/' }, '返回首页')));
  }

  function viewAnalysis(p) {
    setView(loading('正在获取行情、基本面与资讯，并计算指标……'));
    var task;
    if (p.csvId) {
      var rep = state.csvReports[p.csvId];
      task = rep ? Promise.resolve(rep) : Promise.reject(new Error('导入的数据已失效（页面刷新后需要重新导入）'));
    } else {
      task = api('/api/analyze', { params: { key: p.key, q: p.q, kind: p.params.get('kind') || 'auto' } });
    }
    task.then(function (r) {
      if (p.q) history.replaceState(null, '', '#/a/' + encodeURIComponent(r.instrument.key));
      if (!p.csvId) addRecent(r.instrument);
      renderAnalysis(r, p);
    }).catch(function (e) {
      setView(errorCard(e.message, function () { viewAnalysis(p); }));
    });
  }

  function renderAnalysis(r, p) {
    var inst = r.instrument;
    var dg = F.digits(r);
    var name = inst.name || inst.code;
    document.title = name + ' · 投研智能体';
    var priceCls = F.cls(r.price.change_pct);
    var head = h('div', { class: 'inst-head' },
      h('div', null,
        h('h1', { class: 'inst-name' }, name),
        h('div', { class: 'inst-meta' },
          inst.code !== 'CSV' ? h('span', { class: 'badge' }, inst.code) : null,
          h('span', { class: 'badge accent' }, inst.market_label + ' · ' + inst.kind_label),
          r.industry ? h('span', { class: 'badge' }, r.industry) : null)),
      h('div', null,
        h('div', { class: 'inst-price' },
          h('span', { class: 'p num' }, F.num(r.price.last, dg)),
          h('span', { class: 'c num ' + priceCls }, (r.price.change > 0 ? '+' : '') + F.num(r.price.change, dg) + '  ' + F.pp(r.price.change_pct)),
          h('span', { class: 'muted small' }, r.currency_label)),
        h('div', { class: 'sources' }, (r.is_nav ? '净值日期 ' : '数据日期 ') + r.as_of + (r.intraday ? '（盘中，未收盘）' : '') + ' · 来源：' +
          Object.keys(r.sources).map(function (k) { return k + ' ' + r.sources[k]; }).join('，'))),
      h('div', { class: 'inst-actions row no-print' },
        inst.code !== 'CSV' ? h('button', { class: 'btn btn-sm', type: 'button', onclick: function () { addCompare(inst); } }, '加入对比') : null,
        inst.code !== 'CSV' ? h('a', { class: 'btn btn-sm', href: '/api/analyze/markdown?key=' + encodeURIComponent(inst.key) }, '导出报告') : null,
        h('button', { class: 'btn btn-sm', type: 'button', onclick: function () { window.print(); } }, '打印')));

    var warnings = r.warnings && r.warnings.length ? h('div', { class: 'notice-box warn', style: { marginBottom: '16px' } },
      h('strong', null, '部分数据未取到，分析会相应受限：'), h('ul', null, r.warnings.map(function (w) { return h('li', null, w); }))) : null;

    var quantTab = h('div');
    var aiTab = h('div', { hidden: true });
    var tabBtns = {};
    function showTab(which) {
      quantTab.hidden = which !== 'quant';
      aiTab.hidden = which !== 'ai';
      tabBtns.quant.classList.toggle('on', which === 'quant');
      tabBtns.ai.classList.toggle('on', which === 'ai');
      if (which === 'ai' && !aiTab.dataset.ready) { aiTab.dataset.ready = '1'; aiTab.appendChild(aiPanel(r, p, function (label) { tabBtns.ai.textContent = label; })); }
    }
    tabBtns.quant = h('button', { type: 'button', class: 'on', onclick: function () { showTab('quant'); } }, '量化分析');
    tabBtns.ai = h('button', { type: 'button', onclick: function () { showTab('ai'); } }, 'AI 深度分析');
    var tabs = h('div', { class: 'seg no-print', style: { marginBottom: '16px' } }, tabBtns.quant, tabBtns.ai);

    var left = h('div', { class: 'stack' }, chartCard(r), dimsCard(r), returnsCard(r), techCard(r),
      r.fund ? fundCard(r) : r.fundamentals ? fundamentalsCard(r) : null, newsCard(r));
    var right = h('div', { class: 'stack side' },
      ratingCard(r, function () { showTab('ai'); window.scrollTo({ top: 0, behavior: 'smooth' }); }), keyStatsCard(r));
    quantTab.appendChild(h('div', { class: 'grid cols-main' }, left, right));
    setView(head, warnings, tabs, quantTab, aiTab);
    var jobs = LS.get('jobs', {});
    if (p.params.get('tab') === 'ai' || jobs[inst.key]) showTab('ai');
  }

  function ratingCard(r, onAI) {
    var s = r.scores;
    var steps = [['Sell', '卖出'], ['Underweight', '减持'], ['Hold', '持有'], ['Overweight', '增持'], ['Buy', '买入']];
    return card('量化评级', '规则模型 · 不用大模型',
      h('div', { class: 'rating-card' },
        h('div', { class: 'score-line' }, h('span', { class: 'score' }, s.composite.toFixed(1)), h('span', { class: 'score-of' }, '/ 100　中性为 50')),
        h('div', { class: 'ladder', role: 'img', 'aria-label': '评级：' + s.rating.label },
          steps.map(function (st) { return h('span', { class: st[0] === s.rating.code ? 'on' : '' }, st[1]); })),
        h('p', { class: 'small t2', style: { margin: '6px 0 0' } }, s.rating.meaning + '。置信度：' + s.confidence +
          (s.confidence_reasons && s.confidence_reasons.length ? '（' + s.confidence_reasons.join('；') + '）' : '')),
        h('div', { class: 'procon' },
          s.pros.map(function (x) { return h('div', { class: 'item' }, h('span', { class: 'mark up' }, '+'), h('span', null, x.text)); }),
          s.cons.map(function (x) { return h('div', { class: 'item' }, h('span', { class: 'mark down' }, '−'), h('span', null, x.text)); })),
        h('button', { class: 'btn btn-primary', type: 'button', style: { width: '100%', marginTop: '16px' }, onclick: onAI }, '让 AI 投研团队深入分析 →'),
        h('p', { class: 'small muted', style: { margin: '10px 0 0' } }, '评分只反映价格、财务等可量化数据，不含新闻与定性判断；仅供研究参考。')));
  }

  function keyStatsCard(r) {
    var m = r.metrics['1y'] || r.metrics.all || {};
    var items = [
      ['近1年收益', F.pct(r.returns['1y']), F.cls(r.returns['1y'])],
      ['今年以来', F.pct(r.returns.ytd), F.cls(r.returns.ytd)],
      ['年化波动', F.pct(m.volatility, 1, false), ''],
      ['最大回撤', F.pct(m.max_drawdown, 1), ''],
      ['夏普比率', F.num(m.sharpe), ''],
      ['贝塔', F.num(m.beta), '']
    ];
    var q = r.quote || {};
    if (r.kind === 'stock') {
      items.push(['市盈率(动)', F.num(q.pe), '']);
      items.push(['市净率', F.num(q.pb), '']);
      items.push(['总市值', F.money(q.total_cap), '']);
    }
    if (r.fund && r.fund.profile) {
      items.push(['规模', F.num(r.fund.profile.scale) + ' 亿', '']);
      if (r.fund.profile.rank) items.push(['近3月同类', r.fund.profile.rank + '/' + r.fund.profile.rank_total, '']);
    }
    return card('关键数据', (r.metrics['1y'] ? '风险指标为近一年' : '风险指标为全部数据'),
      h('dl', { class: 'kv' }, items.map(function (it) { return h('div', null, h('dt', null, it[0]), h('dd', { class: it[2] }, it[1])); })));
  }

  function chartCard(r) {
    var c = r.chart;
    var host = h('div');
    var table = h('div', { class: 'table-wrap', hidden: true, style: { marginTop: '12px' } });
    var chart = null;
    var ranges = [[60, '3月'], [120, '半年'], [250, '1年'], [750, '3年'], [c.dates.length, '全部']].filter(function (x, i, arr) {
      return x[0] <= c.dates.length || i === arr.length - 1;
    });
    var tools = h('div', { class: 'chart-tools' },
      seg(ranges, 120 <= c.dates.length ? 120 : c.dates.length, function (v) { chart.set('range', v); }),
      seg([['ma', '均线'], ['boll', '布林'], ['none', '无叠加']], 'ma', function (v) { chart.set('overlay', v); }),
      r.is_nav ? seg([['none', '无指标'], ['macd', 'MACD'], ['rsi', 'RSI']], 'none', function (v) { chart.set('ind', v); })
        : seg([['macd', 'MACD'], ['rsi', 'RSI'], ['kdj', 'KDJ'], ['none', '无']], 'macd', function (v) { chart.set('ind', v); }),
      c.benchmark ? seg([['price', r.is_nav ? '净值' : 'K线'], ['relative', '对比 ' + (r.benchmark ? r.benchmark.name : '基准')]], 'price', function (v) { chart.set('mode', v); }) : null,
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn btn-sm', type: 'button', onclick: function () {
        table.hidden = !table.hidden;
        if (!table.hidden && !table.firstChild) table.appendChild(dataTable(r));
      } }, '数据表'));
    var cardEl = card(r.is_nav ? '净值走势' : '价格走势', (r.is_nav ? '单位净值；收益按复权净值计算' : '前复权') + ' · 悬停或用方向键查看每日数据', tools, host, table);
    requestAnimationFrame(function () {
      chart = new window.TYChart.PriceChart(host, c, {
        isNav: r.is_nav, digits: F.digits(r), volumeUnit: r.volume_unit, name: r.instrument.name || r.instrument.code,
        benchName: r.benchmark ? r.benchmark.name : '基准', range: 120
      });
      onCleanup(function () { chart.destroy(); });
    });
    return cardEl;
  }

  function dataTable(r) {
    var c = r.chart, dg = F.digits(r), n = c.dates.length;
    var rows = [];
    for (var i = n - 1; i >= Math.max(1, n - 30); i--) {
      var chg = c.close[i - 1] ? c.close[i] / c.close[i - 1] - 1 : null;
      rows.push(h('tr', null, h('td', null, c.dates[i]),
        r.is_nav ? null : h('td', { class: 'n' }, F.num(c.open[i], dg)),
        r.is_nav ? null : h('td', { class: 'n' }, F.num(c.high[i], dg)),
        r.is_nav ? null : h('td', { class: 'n' }, F.num(c.low[i], dg)),
        h('td', { class: 'n' }, F.num(c.close[i], dg)),
        h('td', { class: 'n ' + F.cls(chg) }, F.pct(chg)),
        r.is_nav ? null : h('td', { class: 'n' }, window.TYChart.compact(c.volume[i]))));
    }
    return h('table', { class: 'tbl' }, h('thead', null, h('tr', null, h('th', null, '日期'),
      r.is_nav ? null : [h('th', { class: 'n' }, '开盘'), h('th', { class: 'n' }, '最高'), h('th', { class: 'n' }, '最低')],
      h('th', { class: 'n' }, r.is_nav ? '单位净值' : '收盘'), h('th', { class: 'n' }, '涨跌幅'),
      r.is_nav ? null : h('th', { class: 'n' }, '成交量（' + r.volume_unit + '）'))), h('tbody', null, rows));
  }

  function dimsCard(r) {
    var dims = r.scores.dimensions;
    return card('维度评分', '点开查看每一分的依据', h('div', { class: 'dims' }, dims.map(function (d) {
      var has = d.score !== null;
      return h('details', { class: 'dim' },
        h('summary', null,
          h('span', { class: 'dl' }, d.label),
          h('span', { class: 'meter' + (has ? '' : ' na'), role: 'img', 'aria-label': d.label + (has ? ' ' + d.score + ' 分' : ' 数据不足') },
            has ? h('i', { style: { width: Math.max(2, d.score) + '%' } }) : null, h('b')),
          h('span', { class: 'sv num' }, has ? d.score.toFixed(0) : '—'),
          h('span', { class: 'chev', 'aria-hidden': 'true' }, '▶')),
        h('div', { class: 'dim-hint' }, d.hint + '；权重 ' + Math.round(d.weight * 100) + '%'),
        h('div', { class: 'evidence' }, d.evidence.length ? d.evidence.map(function (e) {
          return h('div', { class: 'ev' }, h('span', { class: 'imp num ' + F.cls(e.impact) }, (e.impact > 0 ? '+' : e.impact < 0 ? '−' : '±') + Math.abs(e.impact)),
            h('span', null, e.text));
        }) : h('div', { class: 'muted' }, '数据不足，此维度不参与综合评分')));
    })));
  }

  function returnsCard(r) {
    var bname = r.benchmark ? r.benchmark.name : '基准';
    var periods = [['1w', '近1周'], ['1m', '近1月'], ['3m', '近3月'], ['6m', '近6月'], ['ytd', '今年以来'], ['1y', '近1年'], ['3y', '近3年'], ['5y', '近5年']];
    var rows = periods.filter(function (p) { return r.returns[p[0]] !== null && r.returns[p[0]] !== undefined; }).map(function (p) {
      var a = r.returns[p[0]], b = r.benchmark_returns[p[0]];
      var ex = (a !== null && b !== null && b !== undefined) ? a - b : null;
      return h('tr', null, h('td', null, p[1]), h('td', { class: 'n ' + F.cls(a) }, F.pct(a)), h('td', { class: 'n ' + F.cls(b) }, F.pct(b)), h('td', { class: 'n ' + F.cls(ex) }, F.pct(ex)));
    });
    var keys = Object.keys(r.metrics);
    var labels = { '1y': '近1年', '3y': '近3年', all: '全部数据' };
    var spec = [['年化收益', 'cagr', 'pct'], ['年化波动率', 'volatility', 'pct0'], ['最大回撤', 'max_drawdown', 'pct'], ['夏普比率', 'sharpe', 'num'],
      ['索提诺比率', 'sortino', 'num'], ['卡玛比率', 'calmar', 'num'], ['贝塔', 'beta', 'num'], ['相关系数', 'correlation', 'num'],
      ['年化阿尔法', 'alpha', 'pct'], ['信息比率', 'information_ratio', 'num'], ['上涨天数占比', 'win_rate', 'pct0'], ['单日 VaR(95%)', 'var95', 'pct0']];
    var mrows = spec.map(function (s) {
      return h('tr', null, h('td', null, s[0]), keys.map(function (k) {
        var v = r.metrics[k][s[1]];
        return h('td', { class: 'n' }, s[2] === 'pct' ? F.pct(v) : s[2] === 'pct0' ? F.pct(v, 2, false) : F.num(v));
      }));
    });
    var dd = (r.metrics['1y'] || r.metrics.all || {});
    return card('收益与风险', '复权口径 · 无风险利率 ' + (r.risk_free_rate * 100).toFixed(1) + '%',
      h('div', { class: 'grid cols-2' },
        h('div', { class: 'table-wrap' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, h('th', null, '区间'), h('th', { class: 'n' }, '本品种'), h('th', { class: 'n' }, bname), h('th', { class: 'n' }, '超额'))), h('tbody', null, rows))),
        h('div', { class: 'table-wrap' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, h('th', null, '指标'), keys.map(function (k) { return h('th', { class: 'n' }, labels[k]); }))), h('tbody', null, mrows)))),
      dd.drawdown_peak ? h('p', { class: 'small t2', style: { marginBottom: 0 } }, '最大回撤区间：' + dd.drawdown_peak + ' → ' + dd.drawdown_trough + '，' + (dd.drawdown_recover ? dd.drawdown_recover + ' 修复' : '尚未修复')) : null);
  }

  function techCard(r) {
    var ind = r.indicators, lv = r.levels, dg = F.digits(r);
    var kv = [['MA5', ind.ma5], ['MA20', ind.ma20], ['MA60', ind.ma60], ['MA250', ind.ma250], ['DIF', ind.dif, 3], ['DEA', ind.dea, 3],
      ['MACD柱', ind.macd, 3], ['RSI(6)', ind.rsi6, 1], ['RSI(14)', ind.rsi14, 1], ['KDJ-K', ind.k, 1], ['KDJ-D', ind.d, 1], ['KDJ-J', ind.j, 1],
      ['布林上轨', ind.boll_up], ['布林下轨', ind.boll_low], ['ATR(14)', ind.atr14], ['量比', ind.volume_ratio]].filter(function (x) { return x[1] !== null && x[1] !== undefined; });
    var sigs = r.signals.filter(function (s) { return s.dimension === 'trend' || s.dimension === 'momentum'; });
    return card('技术面', '口径同通达信 / 东方财富',
      h('dl', { class: 'kv' }, kv.map(function (x) { return h('div', null, h('dt', null, x[0]), h('dd', null, F.num(x[1], x[2] === undefined ? (x[0] === '量比' ? 2 : dg) : x[2]))); })),
      h('div', { class: 'levels', style: { marginTop: '16px' } },
        h('div', null, h('h4', null, '压力位'), h('ul', null, lv.resistances.length ? lv.resistances.map(function (x) { return h('li', null, h('span', null, x.label), h('b', { class: 'num' }, F.num(x.price, dg))); }) : h('li', { class: 'muted' }, '上方无近期压力'))),
        h('div', null, h('h4', null, '支撑位'), h('ul', null, lv.supports.length ? lv.supports.map(function (x) { return h('li', null, h('span', null, x.label), h('b', { class: 'num' }, F.num(x.price, dg))); }) : h('li', { class: 'muted' }, '下方无近期支撑')))),
      lv.high_52w ? h('p', { class: 'small t2' }, '52 周区间 ' + F.num(lv.low_52w, dg) + ' – ' + F.num(lv.high_52w, dg) +
        (lv.pos_52w !== null ? '，当前位于 ' + Math.round(lv.pos_52w * 100) + '% 位置' : '') + (lv.atr ? '；ATR(14) ' + F.num(lv.atr, dg) + '（' + F.pct(lv.atr_pct, 1, false) + '）' : '')) : null,
      h('h4', { style: { margin: '14px 0 8px', fontSize: '13px' } }, '程序识别的信号'),
      h('div', { class: 'sig-list' }, sigs.map(function (s) {
        var dir = s.impact > 0 ? ['偏多', 'up'] : s.impact < 0 ? ['偏空', 'down'] : ['中性', 'flat'];
        return h('div', { class: 'sig' }, h('span', { class: 'tag ' + dir[1] }, dir[0]), h('span', null, h('b', null, s.name), '：', s.detail));
      })));
  }

  function fundamentalsCard(r) {
    var f = r.fundamentals;
    if (!f.available) return card('基本面', null, h('p', { class: 'muted' }, '没有取到财务数据。'));
    var v = f.valuation, lt = f.latest || {};
    var kv = [['市盈率(动态)', F.num(v.pe)], ['市净率', F.num(v.pb)], ['PEG', F.num(v.peg)], ['总市值', F.money(v.total_cap)], ['流通市值', F.money(v.float_cap)]];
    if (f.latest) {
      kv = kv.concat([['营业收入', F.money(lt.revenue)], ['营收同比', F.pp(lt.revenue_yoy)], ['归母净利润', F.money(lt.net_profit)], ['净利润同比', F.pp(lt.net_profit_yoy)],
        ['ROE' + (lt.roe_annualized !== lt.roe ? '(年化)' : ''), F.pp(lt.roe_annualized).replace('+', '')], ['毛利率', F.pp(lt.gross_margin).replace('+', '')],
        ['净利率', F.pp(lt.net_margin).replace('+', '')], ['资产负债率', F.pp(lt.debt_ratio).replace('+', '')], ['每股收益', F.num(lt.eps, 3)], ['每股经营现金流', F.num(lt.ocf_per_share, 3)]]);
    }
    var hist = f.history || [];
    var sigs = r.signals.filter(function (s) { return ['valuation', 'quality', 'growth'].indexOf(s.dimension) >= 0; });
    return card('基本面', f.latest ? (lt.report_name || lt.report_date) + (f.is_financial ? ' · 金融企业' : '') : '估值',
      h('dl', { class: 'kv' }, kv.map(function (x) { return h('div', null, h('dt', null, x[0]), h('dd', null, x[1])); })),
      hist.length > 1 ? h('div', { class: 'table-wrap', style: { marginTop: '14px' } }, h('table', { class: 'tbl' },
        h('thead', null, h('tr', null, ['报告期', '营收同比', '净利润同比', 'ROE(年化)', '毛利率', '负债率'].map(function (x, i) { return h('th', { class: i ? 'n' : '' }, x); }))),
        h('tbody', null, hist.map(function (x) {
          return h('tr', null, h('td', null, x.report_name || x.report_date), h('td', { class: 'n ' + F.cls(x.revenue_yoy) }, F.pp(x.revenue_yoy, 1)),
            h('td', { class: 'n ' + F.cls(x.net_profit_yoy) }, F.pp(x.net_profit_yoy, 1)), h('td', { class: 'n' }, F.num(x.roe, 1)),
            h('td', { class: 'n' }, F.num(x.gross_margin, 1)), h('td', { class: 'n' }, F.num(x.debt_ratio, 1)));
        })))) : null,
      sigs.length ? h('div', { class: 'sig-list', style: { marginTop: '14px' } }, sigs.map(function (s) {
        var dir = s.impact > 0 ? ['加分', 'up'] : s.impact < 0 ? ['减分', 'down'] : ['中性', 'flat'];
        return h('div', { class: 'sig' }, h('span', { class: 'tag ' + dir[1] }, dir[0]), h('span', null, s.detail));
      })) : null,
      h('p', { class: 'small muted', style: { marginBottom: 0 } }, '估值只看绝对水平，没有做同行业横向比较。'));
  }

  function fundCard(r) {
    var fp = r.fund.profile;
    if (!fp) return card('基金档案', null, h('p', { class: 'muted' }, '没有取到基金档案。'));
    var kv = [['基金类型', fp.fund_type || '—'], ['成立日期', fp.establish_date || '—'], ['基金公司', fp.company || '—'],
      ['规模', fp.scale !== null ? F.num(fp.scale) + ' 亿（' + (fp.scale_date || '—') + '）' : '—'],
      ['申购费率', fp.fee_rate !== null ? F.num(fp.fee_rate) + '%' + (fp.fee_rate_original ? '（原 ' + F.num(fp.fee_rate_original) + '%）' : '') : '—'],
      ['近3月同类排名', fp.rank ? fp.rank + '/' + fp.rank_total + '（超过 ' + Math.round(fp.rank_beat_pct) + '%）' : '—'],
      ['股票仓位', fp.stock_ratio !== null ? F.num(fp.stock_ratio, 1) + '%' : '—'], ['托管人', fp.custodian || '—']];
    return card('基金档案', fp.name,
      h('dl', { class: 'kv' }, kv.map(function (x) { return h('div', null, h('dt', null, x[0]), h('dd', null, x[1])); })),
      fp.managers.length ? h('p', { class: 'small', style: { marginBottom: 0 } }, h('b', null, '基金经理：'),
        fp.managers.map(function (m) { return m.name + (m.tenure ? '（任职 ' + m.tenure + (m.managed_size ? '，管理 ' + m.managed_size : '') + '）' : ''); }).join('；')) : null,
      fp.benchmark ? h('p', { class: 'small t2', style: { marginBottom: 0 } }, h('b', null, '业绩比较基准：'), fp.benchmark) : null,
      fp.strategy ? h('p', { class: 'small t2', style: { marginBottom: 0 } }, h('b', null, '投资策略：'), fp.strategy) : null,
      fp.holdings.length ? h('div', { class: 'table-wrap', style: { marginTop: '14px' } }, h('table', { class: 'tbl' },
        h('thead', null, h('tr', null, h('th', null, '重仓股' + (fp.holdings_period ? '（' + fp.holdings_period + '）' : '')), h('th', null, '代码'), h('th', { class: 'n' }, '占净值'))),
        h('tbody', null, fp.holdings.map(function (x) {
          return h('tr', null, h('td', null, x.name || '—'), h('td', { class: 'num' }, x.code), h('td', { class: 'n' }, x.weight !== null ? F.num(x.weight) + '%' : '—'));
        })))) : null,
      Object.keys(fp.allocation || {}).length ? h('p', { class: 'small t2' }, '资产配置（' + (fp.allocation_date || '最新') + '）：' +
        Object.keys(fp.allocation).map(function (k) { return k + ' ' + F.num(fp.allocation[k], 1) + '%'; }).join('，')) : null);
  }

  function newsCard(r) {
    var items = (r.news || []).slice(0, 10);
    var market = (r.market_news || []).slice(0, 8);
    if (!items.length && !market.length) return null;
    function item(n) {
      var title = h('div', { class: 'nt' }, n.title);
      var link = null;
      if (n.url && /^https?:\/\//.test(n.url)) {
        link = h('a', { href: n.url, target: '_blank', rel: 'noopener noreferrer' });
        link.appendChild(title);
      }
      return h('div', { class: 'news-item' }, link || title, h('div', { class: 'nm' }, [n.time, n.source].filter(Boolean).join(' · ')),
        n.summary && n.summary !== n.title ? h('div', { class: 'ns' }, n.summary.slice(0, 120) + (n.summary.length > 120 ? '…' : '')) : null);
    }
    return card('资讯', '供参考，AI 深度分析会逐条研判',
      items.length ? h('div', { class: 'news' }, items.map(item)) : h('p', { class: 'muted small' }, '没有取到个股新闻。'),
      market.length ? [h('h4', { style: { margin: '18px 0 8px', fontSize: '13px' } }, '市场快讯'), h('div', { class: 'news' }, market.map(item))] : null);
  }

  // ── AI 深度分析面板 ──────────────────────────────────────────
  function aiPanel(r, p, setTabLabel) {
    var c = state.config || {};
    var inst = r.instrument;
    var wrap = h('div', { class: 'stack ai-panel' });
    if (!c.llm_ready) {
      wrap.appendChild(card('AI 深度分析', null,
        h('div', { class: 'notice-box warn' }, '还没有配置大模型：', c.llm_reason || '未配置', '。'),
        h('p', { class: 't2' }, '深度分析会调用大模型，模拟一家投研机构的完整流程：技术面、基本面、资讯三位分析师并行撰写报告 → 多头与空头研究员辩论 → 研究主管形成投资计划 → 交易员给出入场、止损与仓位 → 激进、保守、中性三位风控辩论 → 投资经理给出最终评级。'),
        h('p', { class: 't2' }, '推荐 DeepSeek（国内直连、价格低），默认一次完整分析 11 次模型调用。'),
        h('a', { class: 'btn btn-primary', href: '#/settings' }, '去配置大模型')));
      return wrap;
    }
    if (!c.trusted) {
      wrap.appendChild(card('AI 深度分析', null, h('div', { class: 'notice-box warn' },
        '当前是远程访问，且服务没有设置访问密码。为防止他人消耗你的大模型额度，深度分析只允许在本机使用；在服务器上设置环境变量 APP_PASSWORD 后即可远程使用。')));
      return wrap;
    }
    var hasFund = !!(r.fund || (r.fundamentals && r.fundamentals.available));
    var hasNews = !!((r.news && r.news.length) || (r.market_news && r.market_news.length));
    var defaults = c.defaults || { analysts: ['market', 'fundamentals', 'news'], debate_rounds: 1, risk_rounds: 1 };
    function check(key, label, enabled, note) {
      var box = h('input', { type: 'checkbox', value: key, checked: enabled && defaults.analysts.indexOf(key) >= 0, disabled: !enabled });
      return h('label', { class: 'check', title: enabled ? '' : note }, box, label + (enabled ? '' : '（' + note + '）'));
    }
    var analysts = h('div', { class: 'row' }, check('market', '技术分析师', true), check('fundamentals', r.fund ? '基金研究员' : '基本面分析师', hasFund, '无数据'), check('news', '资讯分析师', hasNews, '无资讯'));
    function rounds(def) { return h('select', null, [1, 2, 3].map(function (n) { return h('option', { value: n, selected: n === def }, n + ' 轮'); })); }
    var debate = rounds(defaults.debate_rounds), risk = rounds(defaults.risk_rounds);
    var shares = h('input', { type: 'number', min: '0', step: 'any', placeholder: '持有数量（股/份）' });
    var cost = h('input', { type: 'number', min: '0', step: 'any', placeholder: '持仓成本价' });
    var cash = h('input', { type: 'number', min: '0', step: 'any', placeholder: '可用资金' });
    var calls = h('span', { class: 'small muted' });
    function updateCalls() {
      var n = analysts.querySelectorAll('input:checked').length || 1;
      calls.textContent = '约 ' + (n + 2 * +debate.value + 2 + 3 * +risk.value + 1) + ' 次模型调用，通常 2–8 分钟';
    }
    [debate, risk].forEach(function (s) { s.addEventListener('change', updateCalls); });
    analysts.addEventListener('change', updateCalls);
    updateCalls();
    var startBtn = h('button', { class: 'btn btn-primary btn-lg', type: 'button' }, '开始 AI 深度分析');
    var form = card('AI 深度分析', '多智能体投研团队（TradingAgents 架构）',
      h('div', { class: 'opts' },
        h('div', null, h('div', { class: 'small t2', style: { marginBottom: '6px' } }, '分析师团队'), analysts),
        h('div', { class: 'row' }, h('label', { class: 'check' }, '多空辩论', debate), h('label', { class: 'check' }, '风控辩论', risk)),
        h('details', null, h('summary', { class: 'small t2', style: { cursor: 'pointer' } }, '我的持仓（可选，填了会给出针对你仓位的操作建议）'),
          h('div', { class: 'pos-grid', style: { marginTop: '8px' } }, shares, cost, cash)),
        h('div', { class: 'small t2' }, '模型：', c.provider_label, '　快模型 ', h('b', null, c.models.quick), '　深度模型 ', h('b', null, c.models.deep), '　', h('a', { href: '#/settings' }, '修改')),
        h('div', { class: 'row' }, startBtn, calls)));
    var progress = h('div');
    wrap.appendChild(form);
    wrap.appendChild(progress);
    var history = h('div');
    wrap.appendChild(history);
    if (inst.code !== 'CSV') {
      api('/api/history', { params: { key: inst.key, limit: 5 } }).then(function (res) {
        if (!res.items.length) return;
        history.appendChild(card('该品种的历史深度分析', null, h('div', { class: 'row' }, res.items.map(function (it) {
          return h('a', { class: 'chip', href: '#/report/' + it.id }, it.created_at + ' · ' + it.rating_label);
        }))));
      }).catch(function () { /* 忽略 */ });
    }

    function num(input) { var v = parseFloat(input.value); return isFinite(v) ? v : null; }
    startBtn.addEventListener('click', function () {
      var picked = Array.prototype.map.call(analysts.querySelectorAll('input:checked'), function (x) { return x.value; });
      var position = (shares.value || cost.value || cash.value) ? { shares: num(shares), cost: num(cost), cash: num(cash) } : null;
      var body = { analysts: picked, debate_rounds: +debate.value, risk_rounds: +risk.value, position: position };
      if (p.csvId) body.csv_id = r.csv_id || p.csvId; else { body.key = inst.key; body.kind = inst.kind; body.name = inst.name; body.secid = inst.secid; }
      startBtn.disabled = true;
      api('/api/deep', { method: 'POST', body: body }).then(function (res) {
        var jobs = LS.get('jobs', {});
        jobs[inst.key] = res.job_id;
        LS.set('jobs', jobs);
        form.hidden = true;
        connectJob(res.job_id, inst.key, progress, setTabLabel);
      }).catch(function (e) {
        startBtn.disabled = false;
        toast(e.message, 'err');
      });
    });

    var existing = LS.get('jobs', {})[inst.key];
    if (existing) {
      api('/api/deep/jobs').then(function (res) {
        var job = (res.jobs || []).filter(function (j) { return j.id === existing; })[0];
        if (!job) { var jobs = LS.get('jobs', {}); delete jobs[inst.key]; LS.set('jobs', jobs); return; }
        form.hidden = job.status === 'running';
        connectJob(existing, inst.key, progress, setTabLabel);
      }).catch(function () { /* 忽略 */ });
    }
    return wrap;
  }

  function connectJob(jobId, instKey, container, setTabLabel) {
    var jv = jobView(container);
    var es = new EventSource('/api/deep/' + jobId + '/events');
    var finished = false;
    es.onmessage = function (m) {
      var ev;
      try { ev = JSON.parse(m.data); } catch (e) { return; }
      jv.handle(ev);
      if (ev.type === 'start') setTabLabel('AI 深度分析 ●');
      if (ev.type === 'done' || ev.type === 'error' || ev.type === 'cancelled') {
        finished = true;
        es.close();
        var jobs = LS.get('jobs', {});
        if (jobs[instKey] === jobId) { delete jobs[instKey]; LS.set('jobs', jobs); }
        setTabLabel(ev.type === 'done' ? 'AI 深度分析 ✓' : 'AI 深度分析');
        if (ev.type === 'done') { toast('AI 深度分析完成'); loadConfig(); }
      }
    };
    es.onerror = function () {
      if (es.readyState === EventSource.CLOSED && !finished) jv.note('与服务的连接已断开。分析仍在后台进行，刷新页面即可重新连接。');
    };
    jv.onCancel(function () {
      api('/api/deep/' + jobId + '/cancel', { method: 'POST' }).then(function () { toast('正在取消……'); }).catch(function (e) { toast(e.message, 'err'); });
    });
    onCleanup(function () { es.close(); jv.destroy(); });
  }

  function fmtPrice(v) {
    if (v === null || v === undefined || !isFinite(v)) return '—';
    return F.num(v, v < 1 ? 4 : v < 10 ? 3 : 2);
  }

  function decisionCard(res) {
    var f = res.final, t = res.trader;
    var unit = res.currency_label || '';
    return card('最终结论', '投资经理 · ' + res.models.deep, h('div', { class: 'decision' },
      h('div', { class: 'dr' }, h('span', { class: 'big' }, f.label), h('span', { class: 'badge' }, f.rating),
        f.confidence ? h('span', { class: 'badge accent' }, '信心 ' + f.confidence) : null,
        h('span', { class: 'spacer' }), res.id && location.hash.indexOf('#/report/') !== 0 ? h('a', { class: 'btn btn-sm', href: '#/report/' + res.id }, '完整报告') : null),
      f.summary ? h('p', { style: { margin: '10px 0 0', fontWeight: 600 } }, f.summary) : null,
      h('div', { class: 'facts' },
        h('span', null, '目标价 ', h('b', null, f.price_target ? fmtPrice(f.price_target) + ' ' + unit : '未给出')),
        h('span', null, '持有期 ', h('b', null, f.time_horizon || '未给出')),
        h('span', null, '研究主管 ', h('b', null, res.research.label)),
        h('span', null, '量化评分 ', h('b', null, res.quant.composite.toFixed(1) + '（' + res.quant.rating.label + '）'))),
      t ? h('dl', { class: 'plan' },
        h('div', null, h('dt', null, '交易员操作'), h('dd', null, t.label)),
        h('div', null, h('dt', null, '入场价'), h('dd', null, fmtPrice(t.entry))),
        h('div', null, h('dt', null, '止损价'), h('dd', null, fmtPrice(t.stop))),
        h('div', null, h('dt', null, '目标价'), h('dd', null, fmtPrice(t.take)))) : null,
      t && t.position ? h('p', { class: 'small t2', style: { margin: '8px 0 0' } }, '仓位建议：' + t.position) : null,
      t && t.warnings && t.warnings.length ? h('div', { class: 'notice-box warn', style: { marginTop: '10px' } }, t.warnings.join('；')) : null,
      h('p', { class: 'small muted', style: { margin: '10px 0 0' } }, '由大模型生成，可能出错；仅供研究参考，不构成投资建议。')));
  }

  function jobView(container) {
    var steps = {};
    var stageEls = {};
    var order = [];
    var decisionBox = h('div');
    var noteBox = h('div');
    var bar = h('div', { class: 'row small t2' });
    var cancelBtn = h('button', { class: 'btn btn-sm btn-danger', type: 'button' }, '取消分析');
    var head = card('分析进度', null, h('div', { class: 'row' }, bar, h('span', { class: 'spacer' }), cancelBtn), noteBox);
    var timeline = h('div', { class: 'timeline' });
    var dataLine = h('div', { class: 'small t2' });
    container.replaceChildren(decisionBox, head, h('section', { class: 'card' }, dataLine, timeline));
    var pending = {};
    var raf = 0;
    var cancelFn = null;
    cancelBtn.addEventListener('click', function () { if (cancelFn) cancelFn(); cancelBtn.disabled = true; });

    function updateBar() {
      var done = order.filter(function (id) { return steps[id].status === 'done'; }).length;
      var running = order.filter(function (id) { return steps[id].status === 'running'; }).map(function (id) { return steps[id].label; });
      bar.replaceChildren(h('span', { class: 'spinner', hidden: !running.length }), '进度 ' + done + ' / ' + order.length + (running.length ? '　正在发言：' + running.join('、') : ''));
    }
    function flush() {
      raf = 0;
      Object.keys(pending).forEach(function (id) {
        var st = steps[id];
        if (!st) return;
        var text = window.MD.stripJson(st.text);
        st.body.innerHTML = window.MD.render(text);
        if (st.status === 'running') {
          var last = st.body.lastElementChild || st.body;
          last.classList.add('cursor');
        }
        st.preview.textContent = text.replace(/[#*|>`-]/g, ' ').replace(/\s+/g, ' ').slice(0, 160);
      });
      pending = {};
    }
    function schedule(id) { pending[id] = true; if (!raf) raf = setTimeout(flush, 120); }

    function makeStep(s) {
      var icon = h('span', { class: 'sicon', 'aria-hidden': 'true' }, '○');
      var meta = h('span', { class: 'smeta' }, '等待中');
      var body = h('div', { class: 'sbody md' });
      var preview = h('div', { class: 'preview' });
      var header = h('header', { role: 'button', tabindex: '0', 'aria-expanded': 'false' }, icon, h('span', { class: 'sname' }, s.label + (s.round ? ' · 第 ' + s.round + ' 轮' : '')), meta);
      var el = h('div', { class: 'step pending collapsed' }, header, preview, body);
      function toggle() {
        if (el.classList.contains('pending')) return;
        el.classList.toggle('collapsed');
        header.setAttribute('aria-expanded', el.classList.contains('collapsed') ? 'false' : 'true');
      }
      header.addEventListener('click', toggle);
      header.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
      steps[s.id] = { el: el, icon: icon, meta: meta, body: body, preview: preview, header: header, text: '', status: 'pending', label: s.label, stage: s.stage };
      order.push(s.id);
      return el;
    }

    function setStatus(id, status, metaText) {
      var st = steps[id];
      if (!st) return;
      st.status = status;
      st.el.classList.remove('pending', 'error');
      if (status === 'running') { st.icon.replaceChildren(h('span', { class: 'spinner' })); st.el.classList.remove('collapsed'); }
      if (status === 'done') { st.icon.textContent = '✓'; }
      if (status === 'error') { st.icon.textContent = '✕'; st.el.classList.add('error'); }
      if (metaText !== undefined) st.meta.textContent = metaText;
      st.header.setAttribute('aria-expanded', st.el.classList.contains('collapsed') ? 'false' : 'true');
      Object.keys(stageEls).forEach(function (k) {
        var ids = order.filter(function (x) { return steps[x].stage === k; });
        var all = ids.every(function (x) { return steps[x].status === 'done' || steps[x].status === 'error'; });
        var any = ids.some(function (x) { return steps[x].status !== 'pending'; });
        stageEls[k].classList.toggle('done', all);
        stageEls[k].classList.toggle('active', any && !all);
      });
      updateBar();
    }

    function renderDecision(res) { decisionBox.replaceChildren(decisionCard(res)); }

    return {
      onCancel: function (fn) { cancelFn = fn; },
      note: function (text) { noteBox.replaceChildren(h('div', { class: 'notice-box warn', style: { marginTop: '10px' } }, text)); },
      destroy: function () { clearTimeout(raf); },
      handle: function (ev) {
        switch (ev.type) {
          case 'stage':
            if (ev.stage === 'data') dataLine.textContent = '正在' + ev.label + '……';
            break;
          case 'report':
            dataLine.textContent = '数据就绪（截至 ' + ev.as_of + '）。量化评分 ' + ev.scores.composite.toFixed(1) + '，' + ev.scores.rating.label + (ev.warnings.length ? '；' + ev.warnings.length + ' 项数据缺失' : '') + '。';
            break;
          case 'start':
            timeline.replaceChildren();
            Object.keys(steps).forEach(function (k) { delete steps[k]; });
            order.length = 0;
            var lastStage = null;
            ev.steps.forEach(function (s) {
              if (s.stage !== lastStage) {
                var titles = { analysts: '① 分析师团队（并行）', research: '② 研究团队：多空辩论 → 研究主管', trading: '③ 交易员', risk: '④ 风控团队辩论', decision: '⑤ 投资经理' };
                var st = h('div', { class: 'stage-title' }, h('span', { class: 'dot' }), titles[s.stage] || s.stage);
                stageEls[s.stage] = st;
                timeline.appendChild(st);
                lastStage = s.stage;
              }
              timeline.appendChild(makeStep(s));
            });
            bar.dataset.models = ev.models.quick + ' / ' + ev.models.deep;
            updateBar();
            break;
          case 'agent_start':
            setStatus(ev.id, 'running', ev.model);
            break;
          case 'delta':
            if (steps[ev.id]) { steps[ev.id].text += ev.text; schedule(ev.id); }
            break;
          case 'agent_done':
            if (steps[ev.id]) {
              steps[ev.id].text = ev.content;
              schedule(ev.id);
              setStatus(ev.id, 'done', '用时 ' + ev.elapsed + ' 秒');
              if (ev.id !== 'portfolio_manager') steps[ev.id].el.classList.add('collapsed');
            }
            break;
          case 'agent_error':
            if (steps[ev.id]) { steps[ev.id].text += '\n\n> 出错：' + ev.message; schedule(ev.id); setStatus(ev.id, 'error', '失败'); }
            break;
          case 'decision':
            break;
          case 'done':
            cancelBtn.hidden = true;
            flush();
            api('/api/history/' + ev.result_id).then(function (item) {
              item.result.id = item.id;
              renderDecision(item.result);
            }).catch(function () { /* 忽略 */ });
            bar.replaceChildren('✓ 分析完成，已存入「历史与复盘」');
            break;
          case 'error':
            cancelBtn.hidden = true;
            flush();
            bar.replaceChildren(h('span', { class: 'bad-mark' }, '分析失败'));
            noteBox.replaceChildren(h('div', { class: 'notice-box err', style: { marginTop: '10px' } }, ev.message));
            break;
          case 'cancelled':
            cancelBtn.hidden = true;
            bar.replaceChildren('已取消');
            break;
        }
      }
    };
  }

  // ── 对比 ─────────────────────────────────────────────────────
  function addCompare(inst) {
    var list = LS.get('compare', []);
    if (list.some(function (x) { return x.key === inst.key; })) { toast('已在对比列表中'); return; }
    if (list.length >= 6) { toast('最多对比 6 个品种', 'err'); return; }
    var used = list.map(function (x) { return x.slot; });
    var slot = [0, 1, 2, 3, 4, 5].filter(function (s) { return used.indexOf(s) < 0; })[0];
    list.push({ key: inst.key, name: inst.name || inst.code, slot: slot });
    LS.set('compare', list);
    toast('已加入对比（' + list.length + '/6）');
  }

  function viewCompare() {
    var period = LS.get('comparePeriod', '1y');
    var chips = h('div', { class: 'row' });
    var result = h('div', { class: 'stack' });
    var runBtn = h('button', { class: 'btn btn-primary', type: 'button' }, '开始对比');
    function renderChips() {
      var list = LS.get('compare', []);
      chips.replaceChildren();
      if (!list.length) chips.appendChild(h('span', { class: 'muted small' }, '还没有添加品种。在下面搜索添加，或在分析页点「加入对比」。'));
      list.forEach(function (x) {
        var dot = h('span', { class: 'key-dot', style: { background: 'var(--s' + (x.slot + 1) + ')' } });
        chips.appendChild(h('button', { class: 'chip', type: 'button', title: '移除', onclick: function () {
          LS.set('compare', LS.get('compare', []).filter(function (y) { return y.key !== x.key; }));
          renderChips();
        } }, dot, x.name, h('span', { class: 'x' }, '×')));
      });
      runBtn.disabled = list.length < 2;
    }
    function run() {
      var list = LS.get('compare', []);
      if (list.length < 2) return;
      result.replaceChildren(loading('正在获取各品种的历史数据……'));
      api('/api/compare', { method: 'POST', body: { keys: list.map(function (x) { return x.key; }), period: period } }).then(function (res) {
        renderCompare(res, list, result);
      }).catch(function (e) { result.replaceChildren(h('div', { class: 'notice-box err' }, e.message)); });
    }
    runBtn.addEventListener('click', run);
    renderChips();
    setView(
      h('h1', { class: 'inst-name', style: { marginBottom: '16px' } }, '多品种对比'),
      card('对比列表', '最多 6 个，股票、基金、ETF、指数可以混合对比',
        chips,
        h('div', { style: { marginTop: '14px' } }, searchBox({ button: '添加', placeholder: '搜索并添加：代码或名称', onPick: function (it) { addCompare(it); renderChips(); } })),
        h('div', { class: 'row', style: { marginTop: '14px' } }, h('span', { class: 'small t2' }, '区间'),
          seg([['3m', '近3月'], ['6m', '近6月'], ['1y', '近1年'], ['3y', '近3年'], ['5y', '近5年']], period, function (v) { period = v; LS.set('comparePeriod', v); run(); }),
          h('span', { class: 'spacer' }), runBtn)),
      result);
    if (LS.get('compare', []).length >= 2) run();
  }

  function renderCompare(res, list, box) {
    var slotOf = {};
    list.forEach(function (x) { slotOf[x.key] = x.slot; });
    var cs = getComputedStyle(document.documentElement);
    var colorFor = function (key) { return cs.getPropertyValue('--s' + ((slotOf[key] || 0) + 1)).trim(); };
    var host = h('div');
    var series = res.series.map(function (s) { return { name: s.name, values: s.values, color: colorFor(s.key) }; });
    var rows = res.rows.map(function (r) {
      var k = r.instrument.key;
      return h('tr', null,
        h('td', null, h('span', { class: 'key-dot', style: { background: 'var(--s' + ((slotOf[k] || 0) + 1) + ')' } }), h('a', { href: '#/a/' + encodeURIComponent(k) }, r.instrument.name || r.instrument.code),
          r.full_window ? null : h('span', { class: 'muted small' }, '（历史不足，起点 ' + r.start + '）')),
        h('td', { class: 'n ' + F.cls(r['return']) }, F.pct(r['return'])),
        h('td', { class: 'n' }, F.pct(r.cagr)),
        h('td', { class: 'n' }, F.pct(r.volatility, 1, false)),
        h('td', { class: 'n' }, F.pct(r.max_drawdown, 1)),
        h('td', { class: 'n' }, F.num(r.sharpe)),
        h('td', { class: 'n' }, F.num(r.calmar)));
    });
    var names = res.rows.map(function (r) { return r.instrument.name || r.instrument.code; });
    var corr = h('table', { class: 'tbl corr' }, h('thead', null, h('tr', null, h('th', null, ''), names.map(function (n) { return h('th', { class: 'n' }, n); }))),
      h('tbody', null, res.correlation.map(function (row, i) {
        return h('tr', null, h('th', null, names[i]), row.map(function (v, j) {
          var bg = v === null || i === j ? null : (v >= 0 ? 'rgba(42,120,214,' : 'rgba(227,73,72,') + Math.min(0.35, Math.abs(v) * 0.35) + ')';
          return h('td', { class: 'n', style: bg ? { background: bg } : null }, v === null ? '—' : v.toFixed(2));
        }));
      })));
    fill(box,
      res.errors && res.errors.length ? h('div', { class: 'notice-box warn' }, '部分品种未能对比：' + res.errors.join('；')) : null,
      card('累计收益走势', '起点归一为 0%，同一纵轴 · 悬停或用方向键查看', host),
      card('关键指标', '区间：' + ({ '3m': '近3月', '6m': '近6月', '1y': '近1年', '3y': '近3年', '5y': '近5年' }[res.period] || res.period) + '（复权）',
        h('div', { class: 'table-wrap' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, ['品种', '区间收益', '年化收益', '年化波动', '最大回撤', '夏普', '卡玛'].map(function (x, i) { return h('th', { class: i ? 'n' : '' }, x); }))), h('tbody', null, rows)))),
      card('收益相关性', '日收益相关系数：越接近 1 走势越同步，分散效果越差；只用双方都交易的日子计算', h('div', { class: 'table-wrap' }, corr)));
    requestAnimationFrame(function () {
      var chart = new window.TYChart.LineChart(host, { dates: res.dates, series: series }, {});
      onCleanup(function () { chart.destroy(); });
    });
  }

  // ── 历史与复盘 ───────────────────────────────────────────────
  function viewHistory() {
    setView(loading());
    api('/api/history', { params: { limit: 200 } }).then(function (res) {
      var items = res.items;
      var stats = h('div', { class: 'stat-row' });
      var tbody = h('tbody');
      var outcomeCells = {};
      items.forEach(function (it) {
        var ret = h('td', { class: 'n muted' }, '—'), ex = h('td', { class: 'n muted' }, '—'), hit = h('td', { class: 'n muted' }, '—');
        outcomeCells[it.id] = [ret, ex, hit];
        tbody.appendChild(h('tr', null,
          h('td', null, it.created_at),
          h('td', null, h('a', { href: '#/a/' + encodeURIComponent(it.inst_key) }, it.name || it.code), h('span', { class: 'muted small' }, ' ' + it.code)),
          h('td', null, h('a', { href: '#/report/' + it.id }, it.rating_label)),
          h('td', { class: 'n' }, it.quant_score !== null ? it.quant_score.toFixed(1) + ' ' + it.quant_rating : '—'),
          h('td', { class: 'n' }, F.num(it.price, it.price < 5 ? 4 : 2)),
          ret, ex, hit));
      });
      function renderStats(outcomes) {
        var decided = 0, hits = 0, excess = [], settled = 0;
        Object.keys(outcomes || {}).forEach(function (k) {
          var o = outcomes[k];
          if (o['return'] !== null && o['return'] !== undefined) settled++;
          if (o.hit === true || o.hit === false) { decided++; if (o.hit) hits++; }
          if (o.excess !== null && o.excess !== undefined) excess.push(o.excess);
        });
        var avg = excess.length ? excess.reduce(function (a, b) { return a + b; }, 0) / excess.length : null;
        stats.replaceChildren(
          h('div', { class: 'stat' }, h('div', { class: 'sl' }, '深度分析次数'), h('div', { class: 'sv' }, String(items.length))),
          h('div', { class: 'stat' }, h('div', { class: 'sl' }, '已有后续行情'), h('div', { class: 'sv' }, outcomes ? String(settled) : '—')),
          h('div', { class: 'stat' }, h('div', { class: 'sl' }, '方向正确率（看多/看空类）'), h('div', { class: 'sv' }, decided ? Math.round(hits / decided * 100) + '%' : '—'), decided ? h('div', { class: 'small muted' }, hits + '/' + decided + ' 次') : null),
          h('div', { class: 'stat' }, h('div', { class: 'sl' }, '平均超额收益'), h('div', { class: 'sv ' + F.cls(avg) }, F.pct(avg))));
      }
      renderStats(null);
      var refresh = h('button', { class: 'btn btn-primary', type: 'button' }, '计算复盘');
      refresh.addEventListener('click', function () {
        refresh.disabled = true;
        refresh.replaceChildren(h('span', { class: 'spinner' }), ' 正在获取最新行情……');
        var ids = items.slice(0, 60).map(function (x) { return x.id; });
        api('/api/history/outcomes', { method: 'POST', body: { ids: ids } }).then(function (res2) {
          Object.keys(res2.outcomes).forEach(function (id) {
            var o = res2.outcomes[id], cells = outcomeCells[id];
            if (!cells) return;
            cells[0].className = 'n ' + F.cls(o['return']); cells[0].textContent = o['return'] === null || o['return'] === undefined ? (o.note || '—') : F.pct(o['return']) + '（' + o.days + '日）';
            cells[1].className = 'n ' + F.cls(o.excess); cells[1].textContent = F.pct(o.excess);
            cells[2].className = 'n'; cells[2].textContent = o.hit === true ? '✓' : o.hit === false ? '✕' : '—';
          });
          renderStats(res2.outcomes);
          refresh.replaceChildren('已更新');
        }).catch(function (e) { toast(e.message, 'err'); refresh.disabled = false; refresh.replaceChildren('计算复盘'); });
      });
      setView(
        h('div', { class: 'row', style: { marginBottom: '16px' } }, h('h1', { class: 'inst-name' }, '历史与复盘'), h('span', { class: 'spacer' }), refresh),
        stats,
        card('全部深度分析', '复盘口径：分析当日收盘买入，持有到最新收盘；超额 = 同期减去基准涨跌',
          items.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null,
            ['时间', '标的', 'AI 评级', '量化评分', '当时价格', '至今收益', '同期超额', '方向'].map(function (x, i) { return h('th', { class: i >= 3 ? 'n' : '' }, x); }))), tbody))
            : h('div', { class: 'empty' }, '还没有深度分析记录。在任意品种的分析页切到「AI 深度分析」即可开始。')),
        h('p', { class: 'small muted' }, '方向正确：评级为买入/增持且跑赢基准，或评级为卖出/减持且跑输基准；「持有」不计入。短期结果受偶然因素影响大，样本多了才有参考价值。'));
    }).catch(function (e) { setView(errorCard(e.message, viewHistory)); });
  }

  function viewReport(id) {
    setView(loading());
    api('/api/history/' + id).then(function (item) {
      var res = item.result, rep = item.report;
      res.id = item.id;
      var inst = res.instrument;
      document.title = (inst.name || inst.code) + ' AI 深度分析 · 投研智能体';
      var decision = h('div', null, decisionCard(res));
      var titles = { market: '技术面分析', fundamentals: rep.fund ? '基金分析' : '基本面分析', news: '资讯与情绪分析' };
      function section(title, text, open) {
        return h('details', { class: 'card', open: open || null }, h('summary', { class: 'card-title', style: { cursor: 'pointer' } }, title),
          h('div', { class: 'md', style: { marginTop: '12px' }, html: window.MD.render(window.MD.stripJson(text || '（无）')) }));
      }
      var del = h('button', { class: 'btn btn-danger', type: 'button' }, '删除');
      del.addEventListener('click', function () {
        if (!confirm('确定删除这条分析记录？')) return;
        api('/api/history/' + id, { method: 'DELETE' }).then(function () { toast('已删除'); location.hash = '#/history'; }).catch(function (e) { toast(e.message, 'err'); });
      });
      setView(
        h('div', { class: 'inst-head' },
          h('div', null, h('h1', { class: 'inst-name' }, (inst.name || inst.code) + ' · AI 深度分析'),
            h('div', { class: 'inst-meta' }, h('span', { class: 'badge' }, inst.code), h('span', { class: 'badge accent' }, inst.market_label + ' · ' + inst.kind_label),
              h('span', { class: 'small muted' }, '生成于 ' + res.finished_at + '，数据截至 ' + res.as_of + '，当时价格 ' + F.num(res.price, res.price < 5 ? 4 : 2) + '，用时 ' + Math.round(res.elapsed) + ' 秒'))),
          h('div', { class: 'inst-actions row no-print' },
            inst.code !== 'CSV' ? h('a', { class: 'btn btn-sm', href: '#/a/' + encodeURIComponent(inst.key) }, '查看最新行情') : null,
            h('a', { class: 'btn btn-sm', href: '/api/history/' + id + '/markdown' }, '下载 Markdown'),
            h('button', { class: 'btn btn-sm', type: 'button', onclick: function () { window.print(); } }, '打印 / 存为 PDF'), del)),
        decision,
        section('投资经理：最终决策', res.final.text, true),
        section('交易员：交易方案', res.trader.text, true),
        section('研究主管：投资计划（' + res.research.label + '）', res.research.text, false),
        Object.keys(res.analysts).map(function (k) { return section(titles[k] || k, res.analysts[k] || ('未完成：' + (res.analyst_errors[k] || ''))); }),
        res.debate.map(function (d) { return section((d.agent === 'bull' ? '多头研究员' : '空头研究员') + ' · 第 ' + d.round + ' 轮', d.text); }),
        res.risk.map(function (d) { return section({ aggressive: '激进型风控', conservative: '保守型风控', neutral: '中性风控' }[d.agent] + ' · 第 ' + d.round + ' 轮', d.text); }),
        card('分析时的量化摘要', null, h('p', { class: 'small t2' }, rep.summary)),
        h('p', { class: 'small muted' }, '模型：' + res.models.quick + '（分析与辩论）／' + res.models.deep + '（研究主管与投资经理）。本报告由大模型自动生成，可能出错，仅供研究参考，不构成投资建议。'));
    }).catch(function (e) { setView(errorCard(e.message)); });
  }

  // ── 设置 ─────────────────────────────────────────────────────
  // ── 每日精选 ───────────────────────────────────────────────

  var CHECK_MARK = { pass: '✓', warn: '!', fail: '✕' };

  function viewDaily(runId, strategy) {
    setView(loading());
    var meta;
    api('/api/daily', { params: { strategy: strategy } }).then(function (m) {
      meta = m;
      return runId ? api('/api/daily/runs/' + encodeURIComponent(runId)) : m.latest;
    }).then(function (p) {
      renderDaily(meta, p, strategy || (p ? p.strategy.key : meta.settings.strategy), !!runId);
    }).catch(function (e) { setView(errorCard(e.message, function () { viewDaily(runId, strategy); })); });
  }

  function renderDaily(meta, p, strategy, archived) {
    var status = h('div', { class: 'daily-status', hidden: true, role: 'status' });
    var runBtn = meta.can_run ? h('button', { class: 'btn btn-primary', type: 'button' }, p && !archived ? '重新生成' : '生成今日精选') : null;
    var timer = null;

    function showStatus(st) {
      if (!st || (!st.running && !st.error)) { status.hidden = true; return; }
      status.hidden = false;
      if (st.running) {
        fill(status, h('div', null, h('span', { class: 'spinner' }), ' ', (st.stage ? st.stage + '：' : '') + (st.message || '')),
          h('div', { class: 'meter' }, h('i', { style: { width: (st.percent || 0) + '%' } })),
          h('div', { class: 'small muted' }, '全市场扫描加逐只体检，大约 1–3 分钟。可以先去别的页面，回来再看。'));
      } else {
        fill(status, h('span', { class: 'bad-mark' }, '上次生成失败：'), st.error);
      }
    }
    function poll() {
      if (timer) return;
      timer = setInterval(function () {
        api('/api/daily/status').then(function (st) {
          showStatus(st);
          if (st.running) return;
          clearInterval(timer); timer = null;
          if (st.error) { if (runBtn) runBtn.disabled = false; return; }
          toast(st.message || '已完成');
          viewDaily(null, strategy);
        }).catch(function () { /* 下次再试 */ });
      }, 1500);
      onCleanup(function () { if (timer) clearInterval(timer); });
    }
    if (runBtn) runBtn.addEventListener('click', function () {
      runBtn.disabled = true;
      api('/api/daily/run', { method: 'POST', body: { strategy: strategy } }).then(function (st) { showStatus(st); poll(); })
        .catch(function (e) { toast(e.message, 'err'); runBtn.disabled = false; });
    });
    if (meta.status.running) { if (runBtn) runBtn.disabled = true; showStatus(meta.status); poll(); }
    else if (meta.status.error) showStatus(meta.status);

    var tools = h('div', { class: 'daily-tools' },
      seg(meta.strategies.map(function (s) { return [s.key, s.label]; }), strategy, function (k) { location.hash = '#/daily?strategy=' + k; }),
      h('span', { class: 'small muted' }, (meta.strategies.filter(function (s) { return s.key === strategy; })[0] || {}).desc || ''));
    if (meta.can_run) {
      var box = h('input', { type: 'checkbox', checked: meta.settings.auto && meta.settings.strategy === strategy });
      box.addEventListener('change', function () {
        api('/api/settings', { method: 'POST', body: { daily_auto: box.checked, daily_strategy: strategy } }).then(function () {
          toast(box.checked ? '已开启：每个交易日 15:45 之后自动生成（软件要开着）' : '已关闭自动生成');
        }).catch(function (e) { toast(e.message, 'err'); box.checked = !box.checked; });
      });
      tools.appendChild(h('label', { class: 'check' }, box, '交易日收盘后自动生成这个风格'));
    }

    var head = h('div', { class: 'row daily-head' },
      h('div', null, h('h1', { class: 'inst-name' }, '每日精选'),
        h('div', { class: 'small muted' }, p
          ? (archived ? '历史记录 · ' : '') + '数据日期 ' + p.as_of + ' · ' + p.strategy.label + ' · 生成于 ' + p.created_at + (p.intraday ? ' · 盘中数据，收盘后可能变化' : '')
          : '收盘后扫一遍全市场，挑出值得关注的股票、ETF 和场外基金')),
      h('span', { class: 'spacer' }),
      archived ? h('a', { class: 'btn', href: '#/daily' }, '回到最新') : null,
      p ? h('a', { class: 'btn', href: '/api/daily/runs/' + encodeURIComponent(p.id) + '/markdown' }, '下载文字版') : null,
      archived ? null : runBtn);

    if (!p) {
      setView(head, tools, status, card(null, null, h('div', { class: 'empty' },
        meta.can_run ? '这个风格还没有生成过。点右上角「生成今日精选」，大约 1–3 分钟。' : '这个风格还没有生成过。')), dailyHistory(null));
      return;
    }
    setView(head, tools, status,
      dailyMarket(p.market),
      p.commentary ? card('今日点评', '大模型根据下面的数据撰写，只引用了数据里的数字',
        h('div', { class: 'md', html: window.MD.render(p.commentary) })) : null,
      dailyStocks(p.stocks), dailyEtfs(p.etfs), dailyFunds(p.funds), dailyHistory(p.id),
      p.warnings && p.warnings.length ? card('数据提示', null, h('ul', { class: 'small muted' }, p.warnings.map(function (w) { return h('li', null, w); }))) : null,
      h('p', { class: 'small muted' }, p.disclaimer));
  }

  function dailyMarket(m) {
    var reg = m.regime;
    var br = m.breadth;
    function boardChips(list) {
      return list.map(function (b) { return h('span', { class: 'badge' }, b.name + ' ', h('span', { class: F.cls(b.change_pct) }, F.pp(b.change_pct))); });
    }
    return card('大盘', null,
      h('div', { class: 'regime ' + (reg.label === '偏强' ? 'is-up' : reg.label === '偏弱' ? 'is-down' : 'is-flat') },
        h('strong', null, '市场温度：' + reg.label), reg.advice,
        h('div', { class: 'small muted' }, reg.notes.join(' · '))),
      m.indices.length ? h('div', { class: 'idx-row' }, m.indices.map(function (i) {
        return h('a', { class: 'idx', href: '#/a/' + encodeURIComponent(i.key) + '?kind=index' },
          h('div', { class: 'small muted' }, i.name), h('div', { class: 'iv' }, F.num(i.price)),
          h('div', { class: 'small ' + F.cls(i.change_pct) }, F.pp(i.change_pct)));
      })) : null,
      br ? h('div', { class: 'small muted' }, '上涨 ' + br.up + ' 家 · 下跌 ' + br.down + ' 家 · 涨停 ' + br.limit_up +
        ' · 跌停 ' + br.limit_down + ' · 成交 ' + F.money(br.amount_yi * 1e8)) : null,
      m.sectors_up.length ? h('div', { class: 'sector-row' }, h('span', { class: 'small muted' }, '领涨行业'), boardChips(m.sectors_up)) : null,
      m.sectors_down.length ? h('div', { class: 'sector-row' }, h('span', { class: 'small muted' }, '领跌行业'), boardChips(m.sectors_down)) : null);
  }

  function lvBox(label, v) {
    return h('div', { class: 'lv' }, h('div', { class: 'small muted' }, label), h('div', { class: 'lvv' }, v === null || v === undefined ? '—' : String(v)));
  }

  function pickBlock(s, n) {
    var d = s.dashboard, lv = d.levels;
    var href = '#/a/' + encodeURIComponent(s.key);
    return h('article', { class: 'pick' },
      h('header', { class: 'pick-head' },
        h('span', { class: 'pick-rank' }, String(n)),
        h('div', null, h('a', { class: 'pick-name', href: href }, s.name),
          h('span', { class: 'small muted' }, ' ' + s.code + (s.industry ? ' · ' + s.industry : ''))),
        h('span', { class: 'spacer' }),
        h('span', { class: 'pick-price' }, F.num(s.price), ' ', h('span', { class: F.cls(s.change_pct) }, F.pp(s.change_pct))),
        h('span', { class: 'badge ' + (d.signal === 'buy' ? 'sig-buy' : 'sig-watch') }, d.signal_label),
        h('span', { class: 'pick-score', title: '最终分 = 全市场因子 45% + 技术信号 25% + 量化体检 30% − 风险扣分' }, s.score.toFixed(0))),
      h('p', { class: 'pick-one' }, d.one_sentence),
      h('ul', { class: 'checks' }, d.checklist.map(function (c) {
        return h('li', { class: 'ck ' + c.status }, h('span', { class: 'ck-mark', 'aria-hidden': 'true' }, CHECK_MARK[c.status]),
          h('span', { class: 'ck-label' }, c.label), h('span', null, c.detail));
      })),
      h('div', { class: 'pick-levels' }, lvBox('理想买点', lv.ideal_buy), lvBox('次优买点', lv.secondary_buy),
        lvBox('止损', lv.stop_loss), lvBox('目标', lv.target),
        lvBox('盈亏比', lv.reward_risk === null || lv.reward_risk === undefined ? null : Number(lv.reward_risk).toFixed(1))),
      h('div', { class: 'pick-advice small' }, h('div', null, h('strong', null, '空仓者：'), d.advice.no_position),
        h('div', null, h('strong', null, '持仓者：'), d.advice.has_position)),
      d.risks.length ? h('div', { class: 'pick-advice small' }, h('div', null, h('strong', null, '风险：'), d.risks.join('；'))) : null,
      h('div', { class: 'row' }, h('a', { class: 'btn btn-sm', href: href }, '完整体检'),
        h('a', { class: 'btn btn-sm', href: href + '?tab=ai' }, 'AI 深度分析'), h('span', { class: 'spacer' }),
        h('span', { class: 'small muted' }, '因子 ' + s.screen_score.toFixed(0) + ' · 技术 ' + s.signal_score.toFixed(0) +
          ' · 体检 ' + s.quant_score.toFixed(0) + (s.penalty ? ' · 风险扣 ' + s.penalty : ''))));
  }

  function dailyStocks(st) {
    var f = st.funnel;
    var reasons = [];
    [f.dropped || {}, f.daily_dropped || {}].forEach(function (obj) {
      Object.keys(obj).forEach(function (k) { reasons.push(h('li', null, k + '：' + obj[k] + ' 只')); });
    });
    return card('精选股票', '全市场 ' + f.universe + ' 只 → 条件过滤后 ' + f.passed_hard + ' → 初选 ' + f.pool + ' → 入选 ' + f.picked,
      st.picks.length ? st.picks.map(function (s, i) { return pickBlock(s, i + 1); })
        : h('div', { class: 'empty' }, '今天没有股票同时满足全部条件，宁缺毋滥。'),
      st.runners_up.length ? h('div', { class: 'sector-row' }, h('span', { class: 'small muted' }, '其他候选'),
        st.runners_up.map(function (r) { return h('a', { class: 'badge', href: '#/a/' + encodeURIComponent(r.key) }, r.name + ' ' + r.score.toFixed(0)); })) : null,
      reasons.length ? h('details', { class: 'small muted', style: { marginTop: '10px' } }, h('summary', null, '其余股票为什么没入选'), h('ul', null, reasons)) : null);
  }

  function dailyEtfs(e) {
    var picked = {};
    e.picks.forEach(function (x) { picked[x.key] = true; });
    var rows = e.ranking.map(function (x) {
      var mo = x.momentum;
      return h('tr', { class: picked[x.key] ? 'hl' : '' },
        h('td', null, h('a', { href: '#/a/' + encodeURIComponent(x.key) + '?kind=etf' }, x.name), h('span', { class: 'small muted' }, ' ' + x.code)),
        h('td', null, x.group),
        [mo.r20, mo.r60, mo.r120].map(function (v) { return h('td', { class: 'n ' + F.cls(v) }, F.pp(v, 1)); }),
        h('td', { class: 'n' }, mo.above_ma20 ? '是' : '否'),
        h('td', { class: 'n' }, F.pp(mo.drawdown_120d, 1)),
        h('td', { class: 'n' }, F.num(mo.score, 1)));
    });
    var chips = e.picks.map(function (x) { return h('a', { class: 'badge accent', href: '#/a/' + encodeURIComponent(x.key) + '?kind=etf' }, x.name); });
    if (e.safe) chips.push(h('a', { class: 'badge', href: '#/a/' + encodeURIComponent(e.safe.key) + '?kind=etf' }, '防守：' + e.safe.name));
    return card('ETF 动量轮动', '按近 60 / 20 / 120 日涨幅排名；只选近 60 日上涨、且站上 20 日线的',
      h('p', null, e.note + '。'), chips.length ? h('div', { class: 'sector-row' }, chips) : null,
      rows.length ? h('div', { class: 'table-wrap', style: { marginTop: '12px' } }, h('table', { class: 'tbl' },
        h('thead', null, h('tr', null, ['ETF', '类别', '近20日', '近60日', '近120日', '站上20日线', '120日最大回撤', '动量分'].map(function (x, i) {
          return h('th', { class: i >= 2 ? 'n' : '' }, x);
        }))), h('tbody', null, rows))) : null);
  }

  function dailyFunds(fs) {
    function kv(label, value, cls) { return h('div', null, h('dt', null, label), h('dd', { class: cls || '' }, value)); }
    return card('场外基金', '看长期业绩：近 3 年同类排名为主，再体检规模、经理任期、回撤和夏普', fs.groups.map(function (g) {
      return h('div', { class: 'fund-group' }, h('h3', null, g.label),
        g.picks.length ? g.picks.map(function (x) {
          var r = x.returns;
          return h('div', { class: 'fund-pick' },
            h('div', { class: 'row' }, h('a', { class: 'pick-name', href: '#/a/' + encodeURIComponent(x.key) }, x.name),
              h('span', { class: 'small muted' }, x.code + (x.type ? ' · ' + x.type : '')), h('span', { class: 'spacer' }),
              h('span', { class: 'pick-score', title: '业绩分 55% + 量化体检 45%' }, x.score.toFixed(0))),
            h('dl', { class: 'kv' }, kv('近1年', F.pp(r.y1, 1), F.cls(r.y1)), kv('近3年', F.pp(r.y3, 1), F.cls(r.y3)),
              kv('近3年最大回撤', F.pct(x.max_drawdown_3y, 1)), kv('夏普（3年）', F.num(x.sharpe_3y)),
              kv('规模', x.scale ? F.num(x.scale, 1) + ' 亿' : '—'), kv('申购费', x.fee || '—')),
            h('div', { class: 'procon' }, x.pros.map(function (t) { return h('div', { class: 'item' }, h('span', { class: 'mark ok-mark' }, '✓'), t); }),
              x.cons.map(function (t) { return h('div', { class: 'item' }, h('span', { class: 'mark bad-mark' }, '!'), t); })));
        }) : h('div', { class: 'small muted' }, '今天没有基金通过全部检查。'),
        g.rejected.length ? h('div', { class: 'small muted', style: { marginTop: '6px' } }, '体检没通过：' +
          g.rejected.map(function (x) { return x.name + '（' + x.reason + '）'; }).join('；')) : null);
    }));
  }

  function dailyHistory(currentId) {
    var listEl = h('div', null, loading());
    var perfEl = h('div');
    var btn = h('button', { class: 'btn', type: 'button' }, '计算历史表现');
    btn.addEventListener('click', function () {
      btn.disabled = true;
      fill(btn, h('span', { class: 'spinner' }), ' 正在获取最新行情……');
      api('/api/daily/performance').then(function (res) {
        fill(btn, '已更新');
        fill(perfEl, perfTable(res));
      }).catch(function (e) { toast(e.message, 'err'); btn.disabled = false; fill(btn, '计算历史表现'); });
    });
    api('/api/daily/runs', { params: { limit: 30 } }).then(function (res) {
      fill(listEl, res.runs.length ? h('div', { class: 'table-wrap', style: { marginTop: '12px' } }, h('table', { class: 'tbl' },
        h('thead', null, h('tr', null, ['数据日期', '风格', '市场', '精选股票', 'ETF'].map(function (x) { return h('th', null, x); }))),
        h('tbody', null, res.runs.map(function (r) {
          return h('tr', { class: r.id === currentId ? 'hl' : '' },
            h('td', null, h('a', { href: '#/daily/' + r.id }, r.as_of)), h('td', null, r.strategy_label), h('td', null, r.regime),
            h('td', null, r.stocks.map(function (x) { return x.name; }).join('、') || '—'),
            h('td', null, r.etfs.map(function (x) { return x.name; }).join('、') || '—'));
        })))) : h('div', { class: 'small muted' }, '还没有历史记录。'));
    }).catch(function (e) { fill(listEl, h('div', { class: 'small muted' }, e.message)); });
    return card('历史表现', '精选当天收盘买入，之后第 1 / 5 / 20 个交易日的收益；超额 = 减去同期沪深300',
      h('div', { class: 'row' }, h('span', { class: 'small muted' }, '每次精选都会保存，日后对照实际走势，才知道这套规则靠不靠谱。'),
        h('span', { class: 'spacer' }), btn), perfEl, listEl);
  }

  function perfTable(res) {
    var cols = [['t1', '第 1 天'], ['t5', '第 5 天'], ['t20', '第 20 天'], ['now', '至今']];
    var rows = Object.keys(res.groups).map(function (g) {
      var G = res.groups[g];
      return h('tr', null, h('td', null, G.label), cols.map(function (c) {
        var s = G[c[0]];
        if (!s || !s.n) return h('td', { class: 'n muted' }, '—');
        return h('td', { class: 'n' }, h('div', { class: F.cls(s.avg) }, F.pct(s.avg)),
          h('div', { class: 'small muted' }, '胜率 ' + Math.round(s.win_rate * 100) + '% · 超额 ' + F.pct(s.avg_excess) + ' · ' + s.n + ' 次'));
      }));
    });
    return [h('div', { class: 'table-wrap', style: { marginTop: '12px' } }, h('table', { class: 'tbl' },
      h('thead', null, h('tr', null, h('th', null, ''), cols.map(function (c) { return h('th', { class: 'n' }, c[1]); }))),
      h('tbody', null, rows))),
      h('p', { class: 'small muted' }, '每格上面是平均收益，下面是胜率（收益为正的比例）、平均超额收益和样本数。样本少于 ' +
        res.min_samples + ' 个时只能看个大概，说明不了规则有效。')];
  }

  function viewSettings() {
    setView(loading());
    api('/api/settings').then(function (s) { renderSettings(s); }).catch(function (e) { setView(errorCard(e.message, viewSettings)); });
  }

  function renderSettings(s) {
    var c = state.config || {};
    var providers = s.providers;
    var current = s.provider;
    var pSelect = h('select', { disabled: s.locks.provider || null });
    var groups = [['cn', '国内可直连'], ['intl', '国外服务（国内通常需要代理）'], ['local', '本机'], ['any', '其他']];
    groups.forEach(function (g) {
      var og = h('optgroup', { label: g[1] });
      providers.filter(function (p) { return p.region === g[0]; }).forEach(function (p) { og.appendChild(h('option', { value: p.key, selected: p.key === current }, p.label)); });
      if (og.children.length) pSelect.appendChild(og);
    });
    var note = h('div', { class: 'provider-note' });
    var keyInput = h('input', { type: 'password', autocomplete: 'off', spellcheck: 'false' });
    var keyHint = h('div', { class: 'field-hint' });
    var baseInput = h('input', { type: 'text', spellcheck: 'false' });
    var quickInput = h('input', { type: 'text', spellcheck: 'false', list: 'modelList' });
    var deepInput = h('input', { type: 'text', spellcheck: 'false', list: 'modelList' });
    var datalist = h('datalist', { id: 'modelList' });
    var effort = h('select', null, ['low', 'medium', 'high', 'xhigh', 'max'].map(function (x) {
      return h('option', { value: x, selected: x === s.claude_effort }, { low: 'low（最快最省）', medium: 'medium', high: 'high（推荐）', xhigh: 'xhigh', max: 'max（最深最贵）' }[x]);
    }));
    var effortField = h('label', { class: 'field' }, h('span', null, 'Claude 推理强度'), effort, h('span', { class: 'field-hint' }, 'Claude 默认自适应思考，强度越高越慢、越贵'));
    var clearKey = h('button', { class: 'btn btn-sm', type: 'button' }, '清除已保存的 Key');
    var status = h('div', { class: 'small', style: { minHeight: '20px' } });

    function fillProvider() {
      var p = providers.filter(function (x) { return x.key === pSelect.value; })[0];
      var pp = s.per_provider[p.key];
      fill(note, p.note || '', p.signup ? [' · ', h('a', { href: p.signup, target: '_blank', rel: 'noopener noreferrer' }, '获取 API Key')] : null);
      keyInput.value = '';
      keyInput.disabled = pp.key_from_env;
      keyInput.placeholder = !p.needs_key && p.key !== 'custom' ? '本机模型不需要 Key' : pp.has_key ? '已保存：' + pp.api_key_masked + '（留空不修改）' : '粘贴 API Key';
      keyHint.textContent = pp.key_from_env ? '已由环境变量 ' + p.key_env + ' 提供（只读）' : p.key_env ? '也可以用环境变量 ' + p.key_env + ' 提供' : '';
      clearKey.hidden = !pp.has_key || pp.key_from_env;
      baseInput.value = pp.base_url || '';
      baseInput.placeholder = p.base_url ? '默认：' + p.base_url : '必填，例如 http://localhost:8000/v1';
      quickInput.value = pp.quick_model || '';
      deepInput.value = pp.deep_model || '';
      quickInput.placeholder = deepInput.placeholder = p.models.length ? '例如 ' + p.models[0] : '填写模型名称';
      datalist.replaceChildren();
      p.models.forEach(function (m) { datalist.appendChild(h('option', { value: m })); });
      effortField.hidden = p.kind !== 'anthropic';
      quickInput.disabled = !!s.locks.quick_model && p.key === s.provider;
      deepInput.disabled = !!s.locks.deep_model && p.key === s.provider;
      baseInput.disabled = !!s.locks.base_url && p.key === s.provider;
    }
    pSelect.addEventListener('change', fillProvider);
    fillProvider();

    function llmPatch() {
      var body = { provider: pSelect.value, base_url: baseInput.value.trim(), quick_model: quickInput.value.trim(), deep_model: deepInput.value.trim(), claude_effort: effort.value };
      if (keyInput.value.trim()) body.api_key = keyInput.value.trim();
      return body;
    }
    var saveBtn = h('button', { class: 'btn btn-primary', type: 'button' }, '保存');
    var testBtn = h('button', { class: 'btn', type: 'button' }, '测试连接');
    saveBtn.addEventListener('click', function () {
      saveBtn.disabled = true;
      api('/api/settings', { method: 'POST', body: llmPatch() }).then(function (ns) {
        s = ns; fillProvider(); toast('已保存'); loadConfig();
        status.replaceChildren(ns.llm_ready ? h('span', { class: 'ok-mark' }, '✓ 配置就绪，可以使用 AI 深度分析') : h('span', { class: 'bad-mark' }, '✕ ' + ns.llm_reason));
      }).catch(function (e) { toast(e.message, 'err'); }).then(function () { saveBtn.disabled = false; });
    });
    testBtn.addEventListener('click', function () {
      testBtn.disabled = true;
      status.replaceChildren(h('span', { class: 'spinner' }), ' 正在调用快模型……');
      api('/api/settings/test', { method: 'POST', body: llmPatch() }).then(function (r) {
        status.replaceChildren(r.ok ? h('span', { class: 'ok-mark' }, '✓ 连接成功：' + r.model + '，回复「' + r.reply + '」，用时 ' + (r.ms / 1000).toFixed(1) + ' 秒')
          : h('span', { class: 'bad-mark' }, '✕ ' + r.message));
      }).catch(function (e) { status.replaceChildren(h('span', { class: 'bad-mark' }, '✕ ' + e.message)); }).then(function () { testBtn.disabled = false; });
    });
    clearKey.addEventListener('click', function () {
      if (!confirm('清除已保存的 API Key？')) return;
      api('/api/settings', { method: 'POST', body: { provider: pSelect.value, api_key: '__clear__' } }).then(function (ns) { s = ns; fillProvider(); toast('已清除'); loadConfig(); }).catch(function (e) { toast(e.message, 'err'); });
    });

    var analystBoxes = [['market', '技术分析师'], ['fundamentals', '基本面 / 基金分析师'], ['news', '资讯分析师']].map(function (a) {
      return h('label', { class: 'check' }, h('input', { type: 'checkbox', value: a[0], checked: s.analysts.indexOf(a[0]) >= 0 }), a[1]);
    });
    function sel(val, opts) { return h('select', null, opts.map(function (o) { return h('option', { value: o[0], selected: String(o[0]) === String(val) }, o[1]); })); }
    var debate = sel(s.debate_rounds, [[1, '1 轮'], [2, '2 轮'], [3, '3 轮']]);
    var risk = sel(s.risk_rounds, [[1, '1 轮'], [2, '2 轮'], [3, '3 轮']]);
    var rf = h('input', { type: 'number', step: '0.1', min: '0', max: '20', value: s.risk_free_rate });
    var temp = h('input', { type: 'number', step: '0.1', min: '0', max: '2', value: s.temperature === null ? '' : s.temperature, placeholder: '默认（不传）' });
    var maxTok = h('input', { type: 'number', step: '256', min: '256', max: '128000', value: s.max_tokens === null ? '' : s.max_tokens, placeholder: '默认（不传）' });
    var timeout = h('input', { type: 'number', step: '10', min: '30', max: '1800', value: s.timeout });
    var saveFlow = h('button', { class: 'btn btn-primary', type: 'button' }, '保存');
    saveFlow.addEventListener('click', function () {
      var body = {
        analysts: analystBoxes.map(function (l) { return l.firstChild; }).filter(function (x) { return x.checked; }).map(function (x) { return x.value; }),
        debate_rounds: +debate.value, risk_rounds: +risk.value, risk_free_rate: parseFloat(rf.value) || 0,
        temperature: temp.value === '' ? null : parseFloat(temp.value), max_tokens: maxTok.value === '' ? null : parseInt(maxTok.value, 10),
        timeout: parseInt(timeout.value, 10) || 300
      };
      if (!body.analysts.length) { toast('至少选择一位分析师', 'err'); return; }
      api('/api/settings', { method: 'POST', body: body }).then(function (ns) { s = ns; toast('已保存'); loadConfig(); }).catch(function (e) { toast(e.message, 'err'); });
    });

    var themeSel = sel(LS.get('theme', 'auto'), [['auto', '跟随系统'], ['light', '浅色'], ['dark', '深色']]);
    themeSel.addEventListener('change', function () { LS.set('theme', themeSel.value); applyTheme(); });
    var updownSel = sel(LS.get('updown', 'red-up'), [['red-up', '红涨绿跌（A股习惯）'], ['green-up', '绿涨红跌（海外习惯）']]);
    updownSel.addEventListener('change', function () { LS.set('updown', updownSel.value); applyTheme(); });

    var checkList = h('div', { class: 'check-list' });
    var checkBtn = h('button', { class: 'btn', type: 'button' }, '开始自检');
    checkBtn.addEventListener('click', function () {
      checkBtn.disabled = true;
      checkList.replaceChildren(loading('逐个探测数据源，约 10 秒……'));
      api('/api/selftest').then(function (res) {
        fill(checkList,
          h('p', { class: 'small t2', style: { margin: '0 0 6px' } }, res.ok + '/' + res.total + ' 个数据源可用。可选后备库：' +
            Object.keys(res.optional).map(function (k) { return k + (res.optional[k] ? ' 已安装' : ' 未安装'); }).join('，')),
          res.checks.map(function (x) {
            return h('div', { class: 'check-item' }, h('span', { class: x.ok ? 'ok-mark' : 'bad-mark' }, x.ok ? '✓' : '✕'),
              h('span', null, h('b', null, x.name), h('div', { class: 'muted' }, x.desc)), h('span', { class: 'cd' }, x.detail), h('span', { class: 'muted num' }, x.ms + 'ms'));
          }));
      }).catch(function (e) { checkList.replaceChildren(h('div', { class: 'notice-box err' }, e.message)); }).then(function () { checkBtn.disabled = false; });
    });

    var locked = !c.trusted ? h('div', { class: 'notice-box warn', style: { marginBottom: '16px' } }, '当前是远程访问且服务没有设置访问密码：设置只能查看，不能修改（防止他人改动你的 Key）。') : null;
    setView(
      h('h1', { class: 'inst-name', style: { marginBottom: '16px' } }, '设置'),
      locked,
      card('大模型', 'AI 深度分析使用；量化分析不需要',
        h('div', { class: 'settings-grid' },
          h('label', { class: 'field' }, h('span', null, '服务商'), pSelect, note),
          h('label', { class: 'field' }, h('span', null, 'API Key'), keyInput, keyHint, clearKey),
          h('label', { class: 'field' }, h('span', null, '快模型'), quickInput, h('span', { class: 'field-hint' }, '分析师、研究员、交易员、风控辩手（调用次数多）')),
          h('label', { class: 'field' }, h('span', null, '深度模型'), deepInput, h('span', { class: 'field-hint' }, '研究主管与投资经理（做最终判断）')),
          h('label', { class: 'field' }, h('span', null, '接口地址（可选）'), baseInput, h('span', { class: 'field-hint' }, '使用中转站、自建服务或代理时填写')),
          effortField, datalist),
        h('div', { class: 'row', style: { marginTop: '16px' } }, saveBtn, testBtn),
        status,
        h('p', { class: 'small muted', style: { marginBottom: 0 } }, 'Key 保存在本机 data/settings.json，不会上传到任何地方，页面上只显示掩码。')),
      card('分析流程', '对应 TradingAgents 的辩论轮数等参数',
        h('div', { class: 'settings-grid' },
          h('div', { class: 'field' }, h('span', { class: 'small', style: { fontWeight: 600 } }, '默认分析师'), h('div', { class: 'row' }, analystBoxes)),
          h('label', { class: 'field' }, h('span', null, '多空辩论轮数'), debate),
          h('label', { class: 'field' }, h('span', null, '风控辩论轮数'), risk),
          h('label', { class: 'field' }, h('span', null, '无风险利率（%）'), rf, h('span', { class: 'field-hint' }, '计算夏普、索提诺、阿尔法时使用')),
          h('label', { class: 'field' }, h('span', null, 'temperature'), temp, h('span', { class: 'field-hint' }, '推理模型多数会忽略；Claude 不使用此参数')),
          h('label', { class: 'field' }, h('span', null, '最大输出长度（token）'), maxTok, h('span', { class: 'field-hint' }, '报告被截断时调大')),
          h('label', { class: 'field' }, h('span', null, '单次调用超时（秒）'), timeout)),
        h('div', { class: 'row', style: { marginTop: '16px' } }, saveFlow)),
      card('显示', '只影响本浏览器',
        h('div', { class: 'settings-grid' },
          h('label', { class: 'field' }, h('span', null, '主题'), themeSel),
          h('label', { class: 'field' }, h('span', null, '涨跌颜色'), updownSel, h('span', { class: 'field-hint' }, 'K 线另以空心 / 实心区分涨跌，色弱也能分清')))),
      card('数据源自检', '网络环境不同，可用的数据源也不同', h('div', { class: 'row', style: { marginBottom: '10px' } }, checkBtn), checkList),
      card('关于', null, h('p', { class: 'small t2', style: { margin: 0 } }, '投研智能体 ' + (c.version || '') + (c.password_protected ? ' · 已启用访问密码' : ' · 未设置访问密码（仅本机可用深度分析与修改设置）') + '。多智能体架构移植自 TauricResearch/TradingAgents（Apache-2.0）。')));
  }

  // ── 导入 CSV ─────────────────────────────────────────────────
  function viewImport() {
    var file = h('input', { type: 'file', accept: '.csv,.txt,text/csv' });
    var name = h('input', { type: 'text', placeholder: '给这份数据起个名字，如「某银行理财A」', maxlength: '40' });
    var currency = h('select', null, h('option', { value: 'CNY' }, '人民币（对比沪深300）'), h('option', { value: 'HKD' }, '港元（对比恒生指数）'), h('option', { value: 'USD' }, '美元（对比标普500）'));
    var btn = h('button', { class: 'btn btn-primary', type: 'button' }, '上传并分析');
    var status = h('div');
    btn.addEventListener('click', function () {
      if (!file.files[0]) { toast('请先选择 CSV 文件', 'err'); return; }
      var fd = new FormData();
      fd.append('file', file.files[0]);
      fd.append('name', name.value.trim() || file.files[0].name.replace(/\.\w+$/, ''));
      fd.append('currency', currency.value);
      btn.disabled = true;
      status.replaceChildren(loading('正在解析并计算……'));
      api('/api/import', { method: 'POST', body: fd }).then(function (rep) {
        state.csvReports[rep.csv_id] = rep;
        location.hash = '#/csv/' + rep.csv_id;
      }).catch(function (e) {
        status.replaceChildren(h('div', { class: 'notice-box err' }, e.message));
        btn.disabled = false;
      });
    });
    setView(
      h('h1', { class: 'inst-name', style: { marginBottom: '16px' } }, '导入数据分析'),
      card('上传 CSV', '数据源覆盖不到的产品——银行理财、私募、信托、自己记录的净值——都可以导入分析',
        h('div', { class: 'settings-grid' },
          h('label', { class: 'field' }, h('span', null, 'CSV 文件'), file, h('span', { class: 'field-hint' }, '至少 20 个交易日，UTF-8 或 GBK 编码都可以')),
          h('label', { class: 'field' }, h('span', null, '名称'), name),
          h('label', { class: 'field' }, h('span', null, '币种'), currency)),
        h('div', { class: 'row', style: { marginTop: '16px' } }, btn), status),
      card('格式说明', null,
        h('p', { class: 'small t2' }, '只需要「日期」和「收盘价/净值」两列，表头中英文都可以（日期/date、收盘/close/单位净值/净值/nav）。有开盘、最高、最低、成交量会画成 K 线，否则画净值线。'),
        h('div', { class: 'md', html: window.MD.render('```\n日期,单位净值\n2024-01-02,1.0234\n2024-01-03,1.0251\n2024-01-04,1.0198\n```') }),
        h('p', { class: 'small muted' }, '数据只在服务内存里保存 2 小时，用于本次分析，不会写入磁盘。')));
  }

  // ── 启动 ─────────────────────────────────────────────────────
  function init() {
    applyTheme();
    $('#themeBtn').addEventListener('click', function () {
      LS.set('theme', effectiveDark() ? 'light' : 'dark');
      applyTheme();
    });
    if (!LS.get('noticeOk', false)) {
      $('#notice').hidden = false;
      $('#noticeOk').addEventListener('click', function () { LS.set('noticeOk', true); $('#notice').hidden = true; });
    }
    window.addEventListener('hashchange', route);
    loadConfig().then(route);
  }
  init();
})();
