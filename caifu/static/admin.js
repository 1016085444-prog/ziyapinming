/* 子牙财鉴 —— 店主管理页。依赖 /shared/common.js（$、el、copyText、showToast）。

   管理口令记在这台设备的 localStorage 里，店主在手机上开一次就不用再输。
   这是店主自己的设备，记住口令的便利大于风险；换设备或借给别人前点「退出登录」。 */

'use strict';

const KEY_STORE = 'caifu_admin';
let adminKey = '';

async function call(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ key: adminKey }, body || {})),
  });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败（' + res.status + '）');
  return data;
}

function linkOf(code) {
  return location.origin + '/?code=' + encodeURIComponent(code);
}

/* 发给买家的整段话。把「一个码一个生日」说在前面，
   能省掉一大半「我想给我妈也测一下」的售后。 */
function messageOf(code) {
  return '【子牙财鉴】您的专属财富测算链接：\n' + linkOf(code) +
         '\n兑换码：' + code +
         '\n温馨提示：一个兑换码绑定一个生日，请填写本人的出生信息；' +
         '出生时间和地点可以修改后重测。';
}

function renderCodes(list) {
  const box = $('#code-list');
  box.innerHTML = '';
  list.forEach((code) => {
    const row = el('div', 'code-row');
    row.append(el('code', null, code));
    const btn = el('button', 'btn-copy', '复制话术');
    btn.type = 'button';
    btn.addEventListener('click', async () => {
      const ok = await copyText(messageOf(code));
      showToast(ok ? '已复制，粘贴发给买家即可' : '复制失败，请手动复制');
      if (ok) row.classList.add('done');
    });
    row.append(btn);
    box.append(row);
  });
  $('#copy-all').hidden = list.length < 2;
  $('#copy-all').onclick = async () => {
    const ok = await copyText(list.map(linkOf).join('\n'));
    showToast(ok ? '已复制 ' + list.length + ' 个链接' : '复制失败');
  };
}

async function login(key) {
  adminKey = key;
  const info = await call('/api/admin/login');
  try { localStorage.setItem(KEY_STORE, key); } catch (_) {}
  $('#login-card').hidden = true;
  $('#panel').hidden = false;
  $('#admin-foot').textContent = '绑定记录存储：' + info.storage +
    (info.storage.indexOf('SQLite') >= 0
      ? '（仅适合本机测试；线上请配置 CAIFU_MYSQL_URL，否则容器重启后绑定会丢）' : '');
}

document.addEventListener('DOMContentLoaded', () => {
  let saved = '';
  try { saved = localStorage.getItem(KEY_STORE) || ''; } catch (_) {}
  if (saved) login(saved).catch(() => { adminKey = ''; });

  $('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = $('#login-error');
    err.hidden = true;
    try {
      await login($('#admin-key').value);
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    }
  });

  $('#gen-btn').addEventListener('click', async () => {
    try {
      const data = await call('/api/admin/codes', { count: Number($('#gen-count').value) });
      renderCodes(data.codes);
    } catch (ex) { showToast(ex.message); }
  });

  let current = '';
  $('#q-btn').addEventListener('click', async () => {
    const box = $('#q-result');
    $('#reset-btn').hidden = true;
    try {
      const d = await call('/api/admin/lookup', { code: $('#q-code').value });
      current = d.code;
      box.innerHTML = '';
      box.append(el('b', null, d.code));
      if (!d.valid) {
        box.append(el('p', 'bad', '无效：不是本店签发的码（或抄错了）'));
      } else if (!d.bound) {
        box.append(el('p', null, '有效 · 尚未使用'));
      } else {
        box.append(el('p', null, '已绑定生日 · 首次使用 ' + d.bound_at),
                   el('p', null, '最近打开 ' + d.last_at + ' · 共测算 ' + d.uses + ' 次'));
        $('#reset-btn').hidden = false;
      }
      box.hidden = false;
    } catch (ex) { showToast(ex.message); }
  });

  $('#reset-btn').addEventListener('click', async () => {
    if (!current || !confirm('确定重置 ' + current + '？重置后买家下次测算会重新绑定生日。')) return;
    try {
      await call('/api/admin/reset', { code: current });
      showToast('已重置，买家可以重新填写生日了');
      $('#reset-btn').hidden = true;
      $('#q-result').hidden = true;
    } catch (ex) { showToast(ex.message); }
  });

  $('#logout').addEventListener('click', () => {
    try { localStorage.removeItem(KEY_STORE); } catch (_) {}
    location.reload();
  });
});
