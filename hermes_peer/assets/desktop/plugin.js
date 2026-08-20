import { jsxs as u, jsx as a } from "react/jsx-runtime";
import { useState as y, useEffect as v } from "react";
function P(r) {
  return {
    health: () => r.rest("/health"),
    metrics: () => r.rest("/metrics"),
    peers: () => r.rest("/peers"),
    summary: () => r.rest("/peers/summary"),
    groups: () => r.rest("/groups"),
    createGroup: (e) => r.rest("/groups", { method: "POST", body: { name: e } }),
    groupMembers: (e) => r.rest(`/groups/${e}/members`),
    addMember: (e, t) => r.rest(`/groups/${e}/members`, { method: "POST", body: { agent_id: t } }),
    broadcastOutcomes: (e) => r.rest(`/broadcasts/${e}`),
    inbox: () => r.rest("/inbox"),
    requests: () => r.rest("/requests"),
    requestDetail: (e) => r.rest(`/requests/${e}`),
    respond: (e, t, s = "") => r.rest(`/requests/${e}/respond`, {
      method: "POST",
      body: { action: t, detail: s }
    }),
    send: (e, t) => r.rest(`/peers/${e}/messages`, {
      method: "POST",
      body: { content: t }
    }),
    policy: (e, t) => r.rest(`/peers/${e}/policy`, {
      method: "POST",
      body: { policy: t }
    }),
    onEvents: (e) => r.socket("/events", (t) => e(t))
  };
}
function $() {
  return { loading: !0, error: null, peers: [], requests: [], summary: null, lastUpdated: null };
}
function S(r, e = Date.now()) {
  if (!r) return "—";
  const t = Date.parse(r);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.floor((e - t) / 1e3));
  if (s < 2) return "just now";
  if (s < 60) return `${s}s ago`;
  const n = Math.floor(s / 60);
  return n < 60 ? `${n}m ago` : `${Math.floor(n / 60)}h ago`;
}
function k(r) {
  var o;
  const e = r.summary;
  if (!e || (e.total ?? 0) < 2) return "";
  const t = (o = (e.peers || []).find((h) => h.peer_id === e.you_peer_id)) == null ? void 0 : o.name, s = [], n = e.active_count ?? 0, i = e.idle_count ?? 0, c = e.offline_count ?? 0;
  return n > 0 && s.push(`● ${n} Live`), i > 0 && s.push(`○ ${i} Idle`), c > 0 && s.push(`× ${c} Offline`), t && s.push(`you: ${t}`), r.lastUpdated != null && e.last_updated && s.push(`live ${S(e.last_updated)}`), s.join(" · ");
}
function q(r, e) {
  let t = 0;
  return async function() {
    var l;
    const n = ++t;
    e({ ...$(), loading: !0 });
    const i = await Promise.allSettled([r.peers(), r.requests(), r.summary()]);
    if (n !== t) return;
    const [c, o, h] = i, p = i.filter((d) => d.status === "rejected"), b = p[0] && "reason" in p[0] ? String(((l = p[0].reason) == null ? void 0 : l.message) ?? p[0].reason) : "";
    e({
      loading: !1,
      error: p.length > 0 ? `${p.length} endpoint(s) failed${b ? `: ${b}` : ""}` : null,
      peers: c.status === "fulfilled" ? c.value.peers : [],
      requests: o.status === "fulfilled" ? o.value.requests : [],
      summary: h.status === "fulfilled" ? h.value : null,
      lastUpdated: Date.now()
    });
  };
}
function w(r, e) {
  return [
    // C1: Focus/Inbox/Dashboard/Group/Broadcast have no host navigation seam
    // yet — ship them disabled rather than rendering buttons that do nothing.
    { key: "f", label: "Focus", run: () => {
    }, disabled: !0 },
    {
      key: "s",
      label: "Send",
      run: (t) => {
        const s = window.prompt(`Send message to ${t.name || t.agent_id.slice(0, 8)}:`);
        s && r.send(t.peer_id, s).then(() => e()).catch((n) => {
          window.alert(`Send failed: ${String((n == null ? void 0 : n.message) || n)}`);
        });
      }
    },
    {
      key: "c",
      label: "Copy ID",
      run: async (t) => {
        try {
          await navigator.clipboard.writeText(t.agent_id || t.peer_id);
        } catch {
        }
      }
    },
    {
      key: "p",
      label: "Policy",
      run: (t) => {
        const s = window.prompt(`Set inbound policy for ${t.name || t.agent_id.slice(0, 8)} (accept|hold|refuse):`, "accept");
        if (!s) return;
        const n = s.trim().toLowerCase();
        if (!["accept", "hold", "refuse"].includes(n)) {
          window.alert(`Invalid policy '${n}'; expected accept|hold|refuse`);
          return;
        }
        r.policy(t.peer_id, n).then(() => e()).catch((i) => {
          window.alert(`Policy failed: ${String((i == null ? void 0 : i.message) || i)}`);
        });
      }
    },
    { key: "i", label: "Inbox", run: () => {
    }, disabled: !0 },
    { key: "d", label: "Dashboard", run: () => {
    }, disabled: !0 },
    { key: "g", label: "Group", run: () => {
    }, disabled: !0 },
    { key: "b", label: "Broadcast", run: () => {
    }, disabled: !0 },
    { key: "r", label: "Refresh", run: () => void e() }
  ];
}
function _(r) {
  const { ctx: e, api: t, state: s, refresh: n } = r, [i, c] = y("peers"), [o, h] = y(null);
  v(() => (n(), t.onEvents(() => void n())), [t, n]);
  const p = [
    ["peers", "Peers"],
    ["groups", "Groups"],
    ["inbox", "Inbox"],
    ["requests", "Requests"],
    ["health", "Health"]
  ], b = (l) => {
    if (!s.peers.length) return;
    const d = s.peers.findIndex((g) => g.peer_id === o), f = (d === -1 ? l === 1 ? -1 : 0 : d + l + s.peers.length) % s.peers.length;
    h(s.peers[f].peer_id);
  };
  return /* @__PURE__ */ u(
    "div",
    {
      className: "hermes-peer-panel",
      onKeyDown: (l) => {
        if (i === "peers")
          if (l.key === "ArrowDown")
            l.preventDefault(), b(1);
          else if (l.key === "ArrowUp")
            l.preventDefault(), b(-1);
          else if (l.key === "Enter" && o) {
            const d = s.peers.find((f) => f.peer_id === o);
            if (d) {
              l.preventDefault();
              const f = w(t, n).find((g) => !g.disabled);
              f && f.run(d);
            }
          } else l.key === "Escape" && h(null);
      },
      children: [
        /* @__PURE__ */ a("div", { className: "hermes-peer-tabs", children: p.map(([l, d]) => /* @__PURE__ */ a(
          "button",
          {
            className: i === l ? "hermes-peer-tab active" : "hermes-peer-tab",
            onClick: () => c(l),
            children: d
          },
          l
        )) }),
        /* @__PURE__ */ u("div", { className: "hermes-peer-body", children: [
          s.loading ? /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "Loading…" }) : null,
          s.error ? /* @__PURE__ */ a("p", { className: "hermes-peer-error", children: s.error }) : null,
          i === "peers" ? /* @__PURE__ */ a(
            C,
            {
              peers: s.peers,
              summary: s.summary,
              selected: o,
              onSelect: h,
              onActivate: (l) => {
                if (!l) return;
                const d = w(t, n).find((f) => f.key === "f");
                d == null || d.run(l);
              }
            }
          ) : null,
          i === "groups" ? /* @__PURE__ */ a(D, { api: t, refresh: n }) : null,
          i === "inbox" ? /* @__PURE__ */ a(E, { api: t }) : null,
          i === "requests" ? /* @__PURE__ */ a(I, { requests: s.requests }) : null,
          i === "health" ? /* @__PURE__ */ a(A, { ctx: e }) : null
        ] }),
        /* @__PURE__ */ a("div", { className: "hermes-peer-actions", "data-testid": "peer-actions", children: w(t, n).map((l) => /* @__PURE__ */ u(
          "button",
          {
            className: "hermes-peer-act",
            "data-action": l.key,
            disabled: !o || l.disabled,
            onClick: () => {
              const d = s.peers.find((f) => f.peer_id === o);
              d && l.run(d);
            },
            children: [
              /* @__PURE__ */ a("kbd", { children: l.key }),
              " ",
              l.label
            ]
          },
          l.key
        )) }),
        /* @__PURE__ */ a("div", { className: "hermes-peer-hint", children: "↑↓ select · Enter act · Esc close" })
      ]
    }
  );
}
function C({
  peers: r,
  summary: e,
  selected: t,
  onSelect: s,
  onActivate: n
}) {
  if (!r.length) return /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "No live peers." });
  const i = (e == null ? void 0 : e.you_peer_id) ?? null;
  return /* @__PURE__ */ a("ul", { className: "hermes-peer-list", role: "listbox", children: r.map((c) => {
    const o = ((e == null ? void 0 : e.peers) || []).some((d) => d.peer_id === c.peer_id && d.offline), h = o ? "offline" : c.status, p = o ? "r" : c.status === "working" ? "g" : c.status === "held" || c.status === "closing" ? "a" : "q", b = c.peer_id === i, l = c.peer_id === t;
    return /* @__PURE__ */ u(
      "li",
      {
        role: "option",
        "aria-selected": l,
        className: `hermes-peer-row${l ? " sel" : ""}${b ? " me" : ""}${o ? " off" : ""}`,
        onClick: () => s(c.peer_id),
        onDoubleClick: () => n(c),
        children: [
          /* @__PURE__ */ a("span", { className: `hermes-peer-dot dot ${p}` }),
          /* @__PURE__ */ u("span", { className: "hermes-peer-row-title", children: [
            c.name || c.agent_id.slice(0, 8),
            b ? /* @__PURE__ */ a("span", { className: "hermes-peer-you", children: "you" }) : null
          ] }),
          /* @__PURE__ */ u("span", { className: "hermes-peer-row-meta", children: [
            c.surface,
            " · ",
            h,
            c.current_activity ? ` · ${c.current_activity}` : ""
          ] })
        ]
      },
      c.agent_id
    );
  }) });
}
function D({ api: r, refresh: e }) {
  const [t, s] = y([]), [n, i] = y("");
  return v(() => {
    r.groups().then((o) => s(o.groups));
  }, [r, e]), /* @__PURE__ */ u("div", { children: [
    /* @__PURE__ */ u("div", { className: "hermes-peer-form", children: [
      /* @__PURE__ */ a("input", { value: n, placeholder: "Group name", onChange: (o) => i(o.target.value) }),
      /* @__PURE__ */ a("button", { onClick: () => {
        n.trim() && r.createGroup(n.trim()).then(() => i("")).then(() => r.groups()).then((o) => s(o.groups));
      }, children: "Create" })
    ] }),
    t.length ? null : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "No groups." }),
    /* @__PURE__ */ a("ul", { className: "hermes-peer-list", children: t.map((o) => /* @__PURE__ */ u("li", { className: "hermes-peer-row", children: [
      /* @__PURE__ */ a("span", { className: "hermes-peer-row-title", children: o.name }),
      /* @__PURE__ */ u("span", { className: "hermes-peer-row-meta", children: [
        o.members,
        " members"
      ] })
    ] }, o.group_id)) })
  ] });
}
function E({ api: r }) {
  const [e, t] = y([]);
  return v(() => {
    r.inbox().then((s) => t(s.messages));
  }, [r]), e.length ? /* @__PURE__ */ a("ul", { className: "hermes-peer-list", children: e.map((s) => /* @__PURE__ */ u("li", { className: "hermes-peer-row", children: [
    /* @__PURE__ */ u("span", { className: "hermes-peer-row-title", children: [
      "[",
      s.state,
      "]"
    ] }),
    /* @__PURE__ */ a("span", { className: "hermes-peer-row-meta", children: s.content.slice(0, 60) })
  ] }, s.message_id)) }) : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "Inbox empty." });
}
function I({
  requests: r
}) {
  return r.length ? /* @__PURE__ */ a("ul", { className: "hermes-peer-list", children: r.map((e) => /* @__PURE__ */ u("li", { className: "hermes-peer-row", children: [
    /* @__PURE__ */ u("span", { className: "hermes-peer-row-title", children: [
      "[",
      e.state,
      "]"
    ] }),
    /* @__PURE__ */ a("span", { className: "hermes-peer-row-meta", children: e.summary })
  ] }, e.request_id)) }) : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "No requests." });
}
function A({ ctx: r }) {
  const [e, t] = y(null);
  return v(() => {
    r.rest("/health").then((s) => t(s));
  }, [r]), e ? /* @__PURE__ */ u("div", { children: [
    /* @__PURE__ */ u("p", { className: "hermes-peer-row-title", children: [
      e.ok ? "Healthy" : "Unhealthy",
      " · backend ",
      e.backend
    ] }),
    e.problems.length ? null : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "No problems." }),
    /* @__PURE__ */ a("ul", { className: "hermes-peer-list", children: e.problems.map((s, n) => /* @__PURE__ */ u("li", { className: "hermes-peer-row", children: [
      /* @__PURE__ */ a("span", { className: "hermes-peer-row-title", children: s.problem }),
      /* @__PURE__ */ a("span", { className: "hermes-peer-row-meta", children: s.remedy })
    ] }, n)) })
  ] }) : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "Checking…" });
}
const G = {
  id: "hermes-peer",
  label: "Hermes Peer",
  activate(r) {
    var f, g;
    const e = P(r), t = [], s = r;
    let n = $(), i = n, c = !1, o = () => {
    };
    const h = q(e, (m) => {
      c || (n = m, i = m, o(m));
    });
    let p = null;
    o = (m) => {
      var N;
      p && (p.textContent = k(m), p.classList.toggle("hermes-peer-pill-off", (((N = m.summary) == null ? void 0 : N.offline_count) ?? 0) > 0));
    };
    const b = () => {
      typeof s.openWorkspace == "function" && s.openWorkspace("hermes-peer", {
        title: "Peers",
        // R2: read live state via stateRef so the panel updates after
        // refreshes instead of freezing on the captured object.
        render: () => _({ ctx: r, api: e, state: i, refresh: h })
      });
    };
    t.push(
      r.register({
        id: "peer-status",
        // H4: the host's STATUSBAR_AREAS uses exact-match keys
        // (statusBar.left/statusBar.right) — 'statusBar' rendered nowhere.
        area: "statusBar.left",
        title: "peer",
        order: 30,
        render: () => {
          const m = document.createElement("button");
          m.className = "hermes-peer-pill", m.textContent = k(n), m.title = "Peers — click for the expanded panel (Ctrl+P)", m.setAttribute("aria-label", "Peer sessions: open expanded panel");
          const N = new AbortController();
          return m.addEventListener("click", b, { signal: N.signal }), t.push(() => N.abort()), p = m, o(n), m;
        }
      })
    ), typeof s.openWorkspace == "function" && t.push(
      r.register({
        id: "peer-open-panel",
        area: "keybinds",
        title: "Open peer panel",
        order: 30,
        render: () => ({
          keybind: "mod+p",
          handler: () => b()
        })
      })
    );
    const l = () => _({
      ctx: r,
      api: e,
      state: i,
      // R2: live state, not a stale capture.
      refresh: h
    });
    t.push(
      r.register({
        id: "peer-panel",
        area: "secondarySidebar",
        title: ((g = (f = r.i18n) == null ? void 0 : f.t) == null ? void 0 : g.call(f, "panel.title")) ?? "Peer",
        order: 30,
        render: l
      })
    );
    const d = e.onEvents(() => {
      h();
    });
    return t.push(d), h(), () => {
      c = !0;
      for (const m of t) m();
      p = null;
    };
  }
};
export {
  G as default
};
