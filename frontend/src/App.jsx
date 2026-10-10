import { MotionConfig } from "motion/react";
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { LiveProvider } from "./live.jsx";
import { OLD_URLS } from "./lib.js";
import { Toasts } from "./toast.jsx";

// Each page is its own chunk, loaded the first time it is opened.
const Forecast = lazy(() => import("./pages/Forecast.jsx"));
const Setup = lazy(() => import("./pages/Setup.jsx"));
const Approvals = lazy(() => import("./pages/Approvals.jsx"));
const Users = lazy(() => import("./pages/Users.jsx"));
const Login = lazy(() => import("./pages/Login.jsx"));

// An old .html address goes to its route, keeping the query (login's ?next= and ?expired=).
function OldUrl({ to }) {
  const { search } = useLocation();
  return <Navigate to={`${to}${search}`} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      {/* Motion follows the device's "reduce motion" setting. */}
      <MotionConfig reducedMotion="user">
        <LiveProvider>
          <Suspense fallback={null}>
            <Routes>
              <Route path="/" element={<Forecast />} />
              <Route path="/setup" element={<Setup />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/users" element={<Users />} />
              <Route path="/login" element={<Login />} />
              {Object.entries(OLD_URLS).map(([file, to]) => <Route key={file} path={`/${file}`} element={<OldUrl to={to} />} />)}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </LiveProvider>
        <Toasts />
      </MotionConfig>
    </BrowserRouter>
  );
}
