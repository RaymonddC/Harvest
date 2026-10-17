import * as Menu from "@radix-ui/react-dropdown-menu";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { can, clearSession, roleLabel } from "../lib.js";
import { Avatar, Dialog, DialogClose } from "../ui.jsx";
import SignInForm from "./SignInForm.jsx";

// Switch to another person without leaving the page. The current session stays until the new
// sign-in succeeds, so closing the dialog changes nothing.
function SwitchUser({ open, onClose, session }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const switched = (next) => {
    onClose();
    if (next.role === "farmer") return location.assign("/call.html"); // the farmer's page is the call client
    toast(`Signed in as ${next.name} (${roleLabel(next)}).`);
    // Stay on this page if the new person may see it; the new state makes the shell re-read the session.
    const allowed = pathname !== "/users" || next.capabilities?.includes("users.admin");
    navigate(allowed ? pathname : "/", { replace: true, state: { switchedAt: Date.now() } });
    return undefined;
  };
  return (
    <Dialog open={open} onClose={onClose} title="Switch user">
      <p className="muted" style={{ margin: "0 0 14px" }}>
        You are signed in as <b>{session.name}</b> ({roleLabel(session)}). Sign in as someone else; you stay on this page.
      </p>
      {open && <SignInForm onSignedIn={switched} exclude={session.user_id} submitLabel="Switch" />}
      <div style={{ marginTop: 12 }}><DialogClose>Cancel</DialogClose></div>
    </Dialog>
  );
}

// Who is signed in, and the ways to change that. On a wide screen it sits at the foot of the
// (sticky) sidebar; on a phone it is the avatar at the right of the top row.
export default function AccountMenu({ session }) {
  const navigate = useNavigate();
  const [switching, setSwitching] = useState(false);
  const signOut = () => {
    clearSession();
    navigate("/login", { replace: true });
  };
  return (
    <>
      <Menu.Root>
        <Menu.Trigger asChild>
          <button type="button" className="account" aria-label={`Account: ${session.name}, ${roleLabel(session)}`}>
            <Avatar name={session.name} person />
            <span className="acc-text"><b>{session.name}</b><span>{roleLabel(session)}</span></span>
            <span className="acc-chev" aria-hidden="true">⌃</span>
          </button>
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="hc-menu acc-menu" side="top" align="start" sideOffset={8} collisionPadding={12}>
            <div className="acc-head">
              <Avatar name={session.name} person />
              <span><b>{session.name}</b><small>{roleLabel(session)}{session.username ? ` · @${session.username}` : ""}</small></span>
            </div>
            <Menu.Separator className="hc-menu-sep" />
            {can("users.admin") && <Menu.Item className="hc-menu-item" onSelect={() => navigate("/users")}>Manage users and roles</Menu.Item>}
            <Menu.Item className="hc-menu-item" onSelect={() => setSwitching(true)}>Switch user</Menu.Item>
            <Menu.Item className="hc-menu-item danger" onSelect={signOut}>Sign out</Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <SwitchUser open={switching} onClose={() => setSwitching(false)} session={session} />
    </>
  );
}
