import { useEffect, useState } from "react";
import { api, apiUrl, can, fmtKg, plainPrice } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, SegToggle } from "../../ui.jsx";

// The mill's payables: every weighbridge delivery in the campaign, newest first, with its net weight, amount, whether it
// is paid (Mark paid, with the transfer reference) and its goods receipt and payment PDF. A delivery recorded from a
// deal ("Record delivery") or on a farmer's card lands here.
const day = (iso) => (iso ? new Date(`${String(iso).slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
const PAGE = 12;

export default function Deliveries({ cid, refreshKey, onOpen }) {
  const act = useAct();
  const [data, setData] = useState(null);
  const [show, setShow] = useState("unpaid");
  const [more, setMore] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    api(`/api/deliveries?campaign=${encodeURIComponent(cid)}`, { method: "GET" }).then((r) => { if (live) setData(r); }).catch(() => {});
    return () => { live = false; };
  }, [cid, refreshKey, tick]);
  if (!data || !data.count) return null;
  const rows = data.deliveries.filter((d) => show === "all" || !d.paid);
  const shown = more ? rows : rows.slice(0, PAGE);
  const cur = data.unpaid.currency;
  const markPaid = async (d) => {
    const ref = window.prompt(`Mark ${d.farmer_name}: ${fmtKg(d.net_kg ?? d.kg)} kg (${d.amount != null ? plainPrice(d.amount, d.currency || cur) : "no amount"}) as paid. Transfer reference (optional):`, "");
    if (ref === null) return;
    await act(() => api(`/api/deliveries/${d.id}/payment`, { method: "PUT", body: { paid: true, ref } }), `${d.farmer_name} marked as paid.`);
    setTick((n) => n + 1);
  };
  return (
    <section className="card deliveries-card" aria-labelledby="deliv-title">
      <div className="card-head">
        <div>
          <h2 id="deliv-title">Deliveries and payments</h2>
          <span className="sub">{data.count} weighed at the mill. {data.unpaid.count ? <><b>{data.unpaid.count} not paid yet: {plainPrice(data.unpaid.amount, cur)}</b>.</> : "Everything is paid."}</span>
        </div>
        <SegToggle label="Show" options={[["unpaid", "Not paid"], ["all", "All"]]} value={show} onChange={(v) => { setShow(v); setMore(false); }} />
      </div>
      {rows.length ? (
        <table className="deliv-table">
          <thead><tr><th>Date</th><th>Farmer</th><th className="r">Net kg</th><th className="r">Amount</th><th>Payment</th><th aria-label="Receipt" /></tr></thead>
          <tbody>
            {shown.map((d) => (
              <tr key={d.id}>
                <td>{day(d.date)}</td>
                <td><button type="button" className="linkish" onClick={() => onOpen?.(d.farmer_id)}>{d.farmer_name}</button>{d.po_number ? <small className="muted"> {d.po_number}</small> : null}</td>
                <td className="r num">{fmtKg(d.net_kg ?? d.kg)}</td>
                <td className="r num">{d.amount != null ? plainPrice(d.amount, d.currency || cur) : "–"}</td>
                <td>{d.paid
                  ? <span className="paid-tag" title={d.payment_ref ? `Ref. ${d.payment_ref}` : undefined}>Paid {day(d.paid_at)}</span>
                  : can("offers.decide") ? <ActButton className="btn sm" busy="Saving…" run={() => markPaid(d)}>Mark paid</ActButton>
                    : <span className="unpaid-tag">Not paid yet</span>}</td>
                <td className="r"><a className="btn sm ghost" href={apiUrl(`/api/deliveries/${d.id}/receipt.pdf`)} download>Receipt PDF</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="small muted" style={{ margin: 0 }}>Every delivery is paid. Choose All to see them.</p>}
      {rows.length > PAGE && <button type="button" className="btn sm ghost" onClick={() => setMore(!more)}>{more ? "Show fewer" : `Show all ${rows.length}`}</button>}
    </section>
  );
}
