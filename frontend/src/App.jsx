import { MotionConfig } from "motion/react";
import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Alerts from "./alerts.jsx";
import { CropProvider, useCrop } from "./campaigns.jsx";
import { ConfirmProvider, UnsavedProvider } from "./dialogs.jsx";
import { LiveProvider } from "./live.jsx";
import { cachedGet, getSession, OLD_URLS } from "./lib.js";
import { Toasts } from "./toast.jsx";

// Each page is its own chunk. They load in the background once the app is up (see Preload), so moving between pages
// never waits for code, and the screen never blanks while a page loads.
const PAGE_CODE = {
  Forecast: () => import("./pages/Forecast.jsx"),
  Overview: () => import("./pages/Overview.jsx"),
  Setup: () => import("./pages/Setup.jsx"),
  Approvals: () => import("./pages/Approvals.jsx"),
  Users: () => import("./pages/Users.jsx"),
  Farmers: () => import("./pages/Farmers.jsx"),
  Agent: () => import("./pages/Agent.jsx"),
  Calls: () => import("./pages/Calls.jsx"),
  Calendar: () => import("./pages/Calendar.jsx"),
  Login: () => import("./pages/Login.jsx"),
};
const Forecast = lazy(PAGE_CODE.Forecast);
const Overview = lazy(PAGE_CODE.Overview);
const Setup = lazy(PAGE_CODE.Setup);
const Approvals = lazy(PAGE_CODE.Approvals);
const Users = lazy(PAGE_CODE.Users);
const Farmers = lazy(PAGE_CODE.Farmers);
const Agent = lazy(PAGE_CODE.Agent);
const Calls = lazy(PAGE_CODE.Calls);
const Calendar = lazy(PAGE_CODE.Calendar);
const Login = lazy(PAGE_CODE.Login);

function Preload() {
  const { cid } = useCrop();
  useEffect(() => {
    if (!cid || !getSession()) return undefined;
    const c = encodeURIComponent(cid);
    const t = setTimeout(() => [`/api/traceability?campaign=${c}`, `/api/track-record?campaign=${c}`,
      `/api/approvals/impact?campaign=${c}`, "/api/crm"].forEach((u) => cachedGet(u).catch(() => {})), 1500);
    return () => clearTimeout(t);
  }, [cid]);
  useEffect(() => {
    const load = () => Object.values(PAGE_CODE).forEach((get) => get().catch(() => {}));
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1200));
    const id = idle(load);
    return () => (window.cancelIdleCallback ? window.cancelIdleCallback(id) : clearTimeout(id));
  }, []);
  return null;
}

// An old .html address goes to its route, keeping the query (login's ?next= and ?expired=).
function OldUrl({ to }) {
  const { search } = useLocation();
  return <Navigate to={`${to}${search}`} replace />;
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      {/* Motion follows the device's "reduce motion" setting. */}
      <MotionConfig reducedMotion="user">
        <LiveProvider>
          <CropProvider>
          <ConfirmProvider>
          <UnsavedProvider>
          <Alerts />
          <Preload />
          <Suspense fallback={null}>
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/forecast" element={<Forecast />} />
              <Route path="/setup" element={<Setup />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/users" element={<Users />} />
              <Route path="/farmers" element={<Farmers />} />
              <Route path="/agent" element={<Agent />} />
              <Route path="/calls" element={<Calls />} />
              <Route path="/calendar" element={<Calendar />} />
              <Route path="/login" element={<Login />} />
              {Object.entries(OLD_URLS).map(([file, to]) => <Route key={file} path={`/${file}`} element={<OldUrl to={to} />} />)}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
          </UnsavedProvider>
          </ConfirmProvider>
          </CropProvider>
        </LiveProvider>
        <Toasts />
      </MotionConfig>
    </BrowserRouter>
  );
}
