(function(){
  const form = document.getElementById('branding-form');
  const box = document.getElementById('brand-preview');
  if (!form || !box) return;
  const fire = () => {
    fetch('/settings/branding/preview', {method:'POST', body: new FormData(form), headers:{'HX-Request':'true'}})
      .then(r => r.text())
      .then(html => { box.innerHTML = html; })
      .catch(() => {});
  };
  form.addEventListener('change', fire);
  form.addEventListener('input', () => { clearTimeout(form._t); form._t = setTimeout(fire, 300); });
  fire();
})();
