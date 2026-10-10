import { createContext, useContext, useEffect, useState } from "react";
import { subscribe } from "./lib.js";

// One live connection for the whole app (server-sent events, or Firestore when configured),
// kept open while the planner moves between pages.
// status: "connecting" until the first message, then "live", "reconnecting" or "error".
const Live = createContext({ state: null, status: "connecting" });

export function LiveProvider({ children }) {
  const [state, setState] = useState(null);
  const [status, setStatus] = useState("connecting");
  useEffect(() => subscribe(setState, setStatus), []);
  return <Live.Provider value={{ state, status }}>{children}</Live.Provider>;
}

export const useLive = () => useContext(Live);
