(function () {
  var url = './runtime-config.js?v=' + Date.now();
  var xhr = new XMLHttpRequest();
  try {
    xhr.open('GET', url, false);
    xhr.send(null);
  } catch (e) {
    return;
  }

  if (xhr.status >= 200 && xhr.status < 300) {
    (0, eval)(xhr.responseText);
    return;
  }
})();
