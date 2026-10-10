import { plainPrice } from "../../lib.js";

// Where the price sits between the floor and the ceiling. A request above the ceiling
// lands in the red stretch past the ceiling mark.
export default function PriceSpot({ price, l, cur }) {
  const span = l.ceiling_price - l.floor_price || 1;
  const top = Math.max(l.ceiling_price, price) + span * 0.25;
  const at = (p) => `${Math.min(Math.max((p - l.floor_price) / (top - l.floor_price), 0), 1) * 100}%`;
  const over = price > l.ceiling_price;
  const under = price < l.floor_price;
  const where = over ? "above the ceiling" : under ? "below the floor" : "inside the range";
  return (
    <div className={`spot ${over || under ? "out" : ""}`} role="img"
      aria-label={`${plainPrice(price, cur)}, ${where}: floor ${plainPrice(l.floor_price, cur)}, ceiling ${plainPrice(l.ceiling_price, cur)}`}
      title={`Floor ${plainPrice(l.floor_price, cur)} · ceiling ${plainPrice(l.ceiling_price, cur)}`}>
      <i className="ok" style={{ width: at(l.ceiling_price) }} />
      <i className="cap" style={{ left: at(l.ceiling_price) }} />
      <i className="dot" style={{ left: at(price) }} />
    </div>
  );
}
