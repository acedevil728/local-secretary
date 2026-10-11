// 앱 껍데기만 캐시한다. API 응답은 화면 쪽에서 마지막 데이터를 보관하고, 끊기면 그걸 보여 준다.
// 화면을 배포할 때마다 바꿀 필요는 없다(네트워크 우선 + 서버가 index.html에 no-cache를 준다).
const CACHE = "pa-shell-v2";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", "/manifest.webmanifest", "/icon.svg"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // 네트워크 우선, 실패하면 캐시
  event.respondWith(
    // navigate 모드 Request에는 옵션을 붙일 수 없어서 URL로 다시 요청한다
    fetch(event.request.url, { cache: "no-cache", credentials: "same-origin" })
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(event.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/"))),
  );
});
