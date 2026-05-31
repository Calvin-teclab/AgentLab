(function () {
  var url = './runtime-config.js?v=' + Date.now();
  var xhr = new XMLHttpRequest();
  xhr.open('GET', url, false);
  xhr.send(null);

  if (xhr.status >= 200 && xhr.status < 300) {
    (0, eval)(xhr.responseText);
    return;
  }

  throw new Error('Failed to load runtime config: HTTP ' + xhr.status);
})();
