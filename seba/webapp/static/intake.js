/* 数据接入向导 */
'use strict';

const ITK = {
  files: [],        // 已上传
  analysis: null,   // 识别结果
  mapping: {},      // role -> {path, fields:{}}
};

const ITK_ROLE_ORDER = ['units', 'roads', 'landuse', 'poi', 'obs'];

function itkOpen() {
  $('intakeModal').hidden = false;
  ITK.files = []; ITK.analysis = null; ITK.mapping = {};
  $('itkFiles').innerHTML = '';
  $('itkResult').innerHTML = '';
  $('itkStep2').hidden = true;
  $('itkStep3').hidden = true;
  $('itkApply').disabled = true;
  $('itkStatus').textContent = '';
  $('itkNotes').innerHTML = '';
}

function itkClose() { $('intakeModal').hidden = true; }

/* 读文件为 base64 */
function itkRead(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result).split(',')[1] || '');
    fr.onerror = rej;
    fr.readAsDataURL(file);
  });
}

async function itkUpload(fileList) {
  const arr = Array.from(fileList || []);
  if (!arr.length) return;
  $('itkStatus').textContent = `正在上传 ${arr.length} 个文件…`;
  const payload = [];
  for (const f of arr) {
    payload.push({ name: f.name, b64: await itkRead(f) });
  }
  try {
    const r = await fetch('/api/intake/upload', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: payload }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || '上传失败');
    ITK.files = ITK.files.concat(j.saved);
    itkRenderFiles();
    await itkAnalyze();
  } catch (e) {
    $('itkStatus').textContent = '上传失败：' + e.message;
  }
}

function itkRenderFiles() {
  const box = $('itkFiles');
  box.innerHTML = ITK.files.map(f =>
    `<span class="filechip">${itkEsc(f.name)}<i>${itkSize(f.size)}</i></span>`).join('');
}

function itkSize(n) {
  if (n > 1048576) return (n / 1048576).toFixed(1) + ' MB';
  if (n > 1024) return (n / 1024).toFixed(0) + ' KB';
  return n + ' B';
}

function itkEsc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* 分析 */
async function itkSample() {
  $('itkStatus').textContent = '正在识别内置的上海示例数据…';
  try {
    const r = await fetch('/api/intake/sample', { method: 'POST' });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || '识别失败');
    ITK.analysis = j;
    itkRenderResult();
    $('itkStatus').textContent = '这是内置上海数据的识别结果，上传你自己的文件也会这样处理';
  } catch (e) {
    $('itkStatus').textContent = '识别失败：' + e.message;
  }
}

async function itkAnalyze() {
  $('itkStatus').textContent = '正在识别文件与字段…';
  try {
    const r = await fetch('/api/intake/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: ITK.files.map(f => f.path) }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || '识别失败');
    ITK.analysis = j;
    itkRenderResult();
    $('itkStatus').textContent = `已识别 ${j.files.length} 个文件`;
  } catch (e) {
    $('itkStatus').textContent = '识别失败：' + e.message;
  }
}

function itkRenderResult() {
  const j = ITK.analysis;
  if (!j) return;
  $('itkStep2').hidden = false;
  $('itkStep3').hidden = false;

  // 每个角色选一个文件（要素最多的），其余作为备选
  ITK.mapping = {};
  const byRole = {};
  for (const f of j.files) {
    if (f.error || !f.role) continue;
    (byRole[f.role] = byRole[f.role] || []).push(f);
  }
  for (const role of ITK_ROLE_ORDER) {
    const list = byRole[role];
    if (!list || !list.length) continue;
    list.sort((a, b) => b.n_features - a.n_features);
    ITK.mapping[role] = { path: list[0].path, fields: { ...(list[0].field_map || {}) } };
  }

  let html = '';
  for (const role of ITK_ROLE_ORDER) {
    const spec = j.role_spec[role];
    if (!spec) continue;
    const list = byRole[role] || [];
    const chosen = ITK.mapping[role];
    const conf = list.length ? Math.round((list[0].role_conf || 0) * 100) : 0;
    const cls = conf >= 80 ? 'good' : (conf >= 50 ? 'warn' : 'bad');

    html += `<div class="rolecard ${chosen ? '' : 'empty'}">`;
    html += `<div class="rolehead">
      <b>${spec.label}</b>
      ${spec.required ? '<em class="req">必需</em>' : '<em class="opt">可选</em>'}
      ${chosen ? `<span class="conf ${cls}">置信 ${conf}%</span>` : '<span class="conf bad">未识别</span>'}
    </div>`;

    if (!chosen) {
      html += `<div class="rolenote">没有找到这类数据（${spec.geom === 'None' ? '表格' : spec.geom + ' 要素'}）。可以跳过，对应因子会自动停用。</div>`;
    } else {
      const opts = list.map((f, i) =>
        `<option value="${i}" ${i === 0 ? 'selected' : ''}>${itkEsc(f.name)}（${f.n_features} 条）</option>`).join('');
      html += `<div class="rolefile">
        <label>使用文件</label>
        <select class="input small" data-role-file="${role}">${opts}</select>
        <span class="muted small">系${itkEsc(list[0].role_reason || '')}</span>
      </div>`;
      html += '<div class="fieldgrid">';
      for (const [fld, label] of Object.entries(spec.fields)) {
        const cur = (chosen.fields || {})[fld] || '';
        const fconf = (list[0].field_conf || {})[fld];
        const cols = ['<option value="">— 不使用 —</option>'].concat(
          list[0].columns.map(c => `<option value="${itkEsc(c)}" ${c === cur ? 'selected' : ''}>${itkEsc(c)}</option>`)
        ).join('');
        html += `<div class="fieldrow">
          <label>${label}</label>
          <select class="input small" data-role="${role}" data-field="${fld}">${cols}</select>
          <span class="muted small">${fconf != null ? '置信 ' + Math.round(fconf * 100) + '%' : ''}</span>
        </div>`;
      }
      html += '</div>';
    }
    html += '</div>';
  }

  // 无法识别的文件
  const bad = j.files.filter(f => f.error || !f.role);
  if (bad.length) {
    html += `<div class="rolecard bad">
      <div class="rolehead"><b>另有 ${bad.length} 个文件未识别</b></div>
      <div class="rolenote">${bad.map(f =>
        `${itkEsc(f.name)}：${itkEsc(f.error || '无法判断类型')}`).join('<br>')}</div>
    </div>`;
  }

  $('itkResult').innerHTML = html;

  // 事件绑定
  $('itkResult').querySelectorAll('select[data-role-file]').forEach(sel => {
    sel.onchange = () => {
      const role = sel.dataset.roleFile;
      const list = byRole[role];
      const f = list[Number(sel.value)];
      ITK.mapping[role] = { path: f.path, fields: { ...(f.field_map || {}) } };
      itkRenderResult();
    };
  });
  $('itkResult').querySelectorAll('select[data-role][data-field]').forEach(sel => {
    sel.onchange = () => {
      const role = sel.dataset.role;
      if (!ITK.mapping[role]) return;
      ITK.mapping[role].fields[sel.dataset.field] = sel.value;
    };
  });

  itkValidate();
}

function itkValidate() {
  const j = ITK.analysis;
  if (!j) return;
  const notes = [];
  let okAll = true;

  for (const role of ITK_ROLE_ORDER) {
    const spec = j.role_spec[role];
    const m = ITK.mapping[role];
    if (spec.required && !m) {
      okAll = false;
      notes.push(`<b>缺少必需数据：${spec.label}</b> — 没有它无法运行，请补上传。`);
      continue;
    }
    if (m) {
      for (const [fld, meta] of Object.entries(spec.fields)) {
        if (meta.required && !m.fields[fld]) {
          okAll = false;
          notes.push(`<b>${spec.label}</b> 缺少必需字段映射：${meta.label}，请在上方下拉框选择。`);
        }
      }
    }
  }

  if (okAll && ITK.mapping.units) {
    const u = ITK.mapping.units;
    notes.push(`将用 <b>${itkBase(u.path)}</b> 作为评估单元边界，通过“${u.fields.district || '—'}”筛选区县。`);
    const opt = ['roads', 'landuse', 'poi', 'obs'].filter(r => ITK.mapping[r]);
    if (opt.length) {
      notes.push('同时接入：' + opt.map(r => j.role_spec[r].label).join('、') + '。');
    } else {
      notes.push('未接入路网等辅助数据，可达性因子将自动停用，仅保留属性类因子。');
    }
  }

  $('itkNotes').innerHTML = notes.map(n => `<div class="note">${n}</div>`).join('');
  $('itkApply').disabled = !okAll;
}

function itkBase(p) { return String(p).split(/[\\/]/).pop(); }

async function itkApply() {
  $('itkStatus').textContent = '正在保存配置…';
  try {
    const body = {
      mapping: ITK.mapping,
      name: $('itkName').value || '我的评估工程',
      cbd_lon: $('itkLon').value || null,
      cbd_lat: $('itkLat').value || null,
    };
    const r = await fetch('/api/intake/apply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || '保存失败');
    $('itkStatus').textContent = '已保存：' + j.saved_to;
    $('itkNotes').innerHTML = `<div class="note ok">${itkEsc(j.note)}</div>` +
      `<div class="note">配置文件：<code>${itkEsc(j.saved_to)}</code></div>`;
    if (j.ran && j.project) {
      // 直接用新数据的结果刷新整个界面
      adopt(j);
      setTimeout(() => { itkClose(); toast(j.note || '已用你的数据完成计算'); }, 600);
    } else {
      toast('配置已保存，重启服务即可用新数据运行');
    }
  } catch (e) {
    $('itkStatus').textContent = '保存失败：' + e.message;
  }
}

/* 绑定 */
/* 支持 #intake 直接打开（便于截图与分享） */
if (location.hash === '#intake') {
  window.addEventListener('load', () => { itkOpen(); itkSample(); });
}

(function itkBind() {
  const btn = $('btnIntake');
  if (btn) btn.onclick = itkOpen;
  const x = $('itkClose'); if (x) x.onclick = itkClose;
  const c = $('itkCancel'); if (c) c.onclick = itkClose;
  const a = $('itkApply'); if (a) a.onclick = itkApply;
  const sm = $('itkSample'); if (sm) sm.onclick = itkSample;

  const drop = $('itkDrop');
  const inp = $('itkFile');
  if (inp) inp.onchange = e => { itkUpload(e.target.files); e.target.value = ''; };

  if (drop) {
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => {
      e.preventDefault(); drop.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
      e.preventDefault(); drop.classList.remove('over');
    }));
    drop.addEventListener('drop', e => {
      if (e.dataTransfer && e.dataTransfer.files) itkUpload(e.dataTransfer.files);
    });
    drop.addEventListener('click', e => {
      if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'LABEL') inp.click();
    });
  }
})();
