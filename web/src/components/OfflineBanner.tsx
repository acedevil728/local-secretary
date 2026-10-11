export function OfflineBanner({ lastSync }: { lastSync: string | null }) {
  const at = lastSync
    ? new Date(lastSync).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "알 수 없음";
  return (
    <div className="banner off" role="status">
      <b>연결이 끊겼어요.</b>
      <span>마지막으로 받은 데이터({at})를 보여 주고 있어요. 다시 연결되면 자동으로 새로 고쳐요. 그동안 완료·미루기는 막아 둘게요.</span>
    </div>
  );
}
