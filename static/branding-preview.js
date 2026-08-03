(function() {
  var form = document.getElementById('branding-form');
  var box = document.getElementById('brand-preview');
  if (!form || !box) return;

  function fire() {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/settings/branding/preview', true);
    xhr.onreadystatechange = function() {
      if (xhr.readyState === 4 && xhr.status === 200) {
        box.innerHTML = xhr.responseText;
      }
    };
    xhr.send(new FormData(form));
  }

  form.addEventListener('change', fire);
  form.addEventListener('input', function() {
    clearTimeout(form._t);
    form._t = setTimeout(fire, 300);
  });

  fire();
})();
