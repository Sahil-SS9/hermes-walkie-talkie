import { jsxs as p, jsx as a } from "react/jsx-runtime";
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
    addMember: (e, s) => r.rest(`/groups/${e}/members`, { method: "POST", body: { agent_id: s } }),
    broadcastOutcomes: (e) => r.rest(`/broadcasts/${e}`),
    inbox: () => r.rest("/inbox"),
    requests: () => r.rest("/requests"),
    requestDetail: (e) => r.rest(`/requests/${e}`),
    respond: (e, s, t = "") => r.rest(`/requests/${e}/respond`, {
      method: "POST",
      body: { action: s, detail: t }
    }),
    send: (e, s) => r.rest(`/peers/${e}/messages`, {
      method: "POST",
      body: { content: s }
    }),
    policy: (e, s) => r.rest(`/peers/${e}/policy`, {
      method: "POST",
      body: { policy: s }
    }),
    onEvents: (e) => r.socket("/events", (s) => e(s))
  };
}
function $() {
  return { loading: !0, error: null, peers: [], requests: [], summary: null, lastUpdated: null };
}
function S(r, e = Date.now()) {
  if (!r) return "—";
  const s = Date.parse(r);
  if (Number.isNaN(s)) return "—";
  const t = Math.max(0, Math.floor((e - s) / 1e3));
  if (t < 2) return "just now";
  if (t < 60) return `${t}s ago`;
  const n = Math.floor(t / 60);
  return n < 60 ? `${n}m ago` : `${Math.floor(n / 60)}h ago`;
}
function k(r) {
  var m;
  const e = r.summary;
  if (!e) return "";
  const s = e.live_count ?? 0;
  if (s < 2) return "";
  const t = (m = (e.peers || []).find((u) => u.peer_id === e.you_peer_id)) == null ? void 0 : m.name, n = [], i = e.active_count ?? 0, c = e.idle_count ?? 0, o = e.offline_count ?? 0;
  return s > 0 && n.push(`● ${s} Live`), i > 0 && i < s && n.push(`${i} working`), c > 0 && n.push(`○ ${c} Idle`), o > 0 && n.push(`× ${o} Offline`), t && n.push(`you: ${t}`), r.lastUpdated != null && e.last_updated && n.push(`live ${S(e.last_updated)}`), n.join(" · ");
}
function q(r, e) {
  let s = 0;
  return async function() {
    var l;
    const n = ++s;
    e({ ...$(), loading: !0 });
    const i = await Promise.allSettled([r.peers(), r.requests(), r.summary()]);
    if (n !== s) return;
    const [c, o, m] = i, u = i.filter((d) => d.status === "rejected"), b = u[0] && "reason" in u[0] ? String(((l = u[0].reason) == null ? void 0 : l.message) ?? u[0].reason) : "";
    e({
      loading: !1,
      error: u.length > 0 ? `${u.length} endpoint(s) failed${b ? `: ${b}` : ""}` : null,
      peers: c.status === "fulfilled" ? c.value.peers : [],
      requests: o.status === "fulfilled" ? o.value.requests : [],
      summary: m.status === "fulfilled" ? m.value : null,
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
      run: (s) => {
        const t = window.prompt(`Send message to ${s.name || s.agent_id.slice(0, 8)}:`);
        t && r.send(s.peer_id, t).then(() => e()).catch((n) => {
          window.alert(`Send failed: ${String((n == null ? void 0 : n.message) || n)}`);
        });
      }
    },
    {
      key: "c",
      label: "Copy ID",
      run: async (s) => {
        try {
          await navigator.clipboard.writeText(s.agent_id || s.peer_id);
        } catch {
        }
      }
    },
    {
      key: "p",
      label: "Policy",
      run: (s) => {
        const t = window.prompt(`Set inbound policy for ${s.name || s.agent_id.slice(0, 8)} (accept|hold|refuse):`, "accept");
        if (!t) return;
        const n = t.trim().toLowerCase();
        if (!["accept", "hold", "refuse"].includes(n)) {
          window.alert(`Invalid policy '${n}'; expected accept|hold|refuse`);
          return;
        }
        r.policy(s.peer_id, n).then(() => e()).catch((i) => {
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
  const { ctx: e, api: s, state: t, refresh: n } = r, [i, c] = y("peers"), [o, m] = y(null);
  v(() => (n(), s.onEvents(() => void n())), [s, n]);
  const u = [
    ["peers", "Peers"],
    ["groups", "Groups"],
    ["inbox", "Inbox"],
    ["requests", "Requests"],
    ["health", "Health"]
  ], b = (l) => {
    if (!t.peers.length) return;
    const d = t.peers.findIndex((g) => g.peer_id === o), f = (d === -1 ? l === 1 ? -1 : 0 : d + l + t.peers.length) % t.peers.length;
    m(t.peers[f].peer_id);
  };
  return /* @__PURE__ */ p(
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
            const d = t.peers.find((f) => f.peer_id === o);
            if (d) {
              l.preventDefault();
              const f = w(s, n).find((g) => !g.disabled);
              f && f.run(d);
            }
          } else l.key === "Escape" && m(null);
      },
      children: [
        /* @__PURE__ */ a("div", { className: "hermes-peer-tabs", children: u.map(([l, d]) => /* @__PURE__ */ a(
          "button",
          {
            className: i === l ? "hermes-peer-tab active" : "hermes-peer-tab",
            onClick: () => c(l),
            children: d
          },
          l
        )) }),
        /* @__PURE__ */ p("div", { className: "hermes-peer-body", children: [
          t.loading ? /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "Loading…" }) : null,
          t.error ? /* @__PURE__ */ a("p", { className: "hermes-peer-error", children: t.error }) : null,
          i === "peers" ? /* @__PURE__ */ a(
            C,
            {
              peers: t.peers,
              summary: t.summary,
              selected: o,
              onSelect: m,
              onActivate: (l) => {
                if (!l) return;
                const d = w(s, n).find((f) => f.key === "f");
                d == null || d.run(l);
              }
            }
          ) : null,
          i === "groups" ? /* @__PURE__ */ a(D, { api: s, refresh: n }) : null,
          i === "inbox" ? /* @__PURE__ */ a(E, { api: s }) : null,
          i === "requests" ? /* @__PURE__ */ a(I, { requests: t.requests }) : null,
          i === "health" ? /* @__PURE__ */ a(A, { ctx: e }) : null
        ] }),
        /* @__PURE__ */ a("div", { className: "hermes-peer-actions", "data-testid": "peer-actions", children: w(s, n).map((l) => /* @__PURE__ */ p(
          "button",
          {
            className: "hermes-peer-act",
            "data-action": l.key,
            disabled: !o || l.disabled,
            onClick: () => {
              const d = t.peers.find((f) => f.peer_id === o);
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
  selected: s,
  onSelect: t,
  onActivate: n
}) {
  if (!r.length) return /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "No live peers." });
  const i = (e == null ? void 0 : e.you_peer_id) ?? null;
  return /* @__PURE__ */ a("ul", { className: "hermes-peer-list", role: "listbox", children: r.map((c) => {
    const o = ((e == null ? void 0 : e.peers) || []).some((d) => d.peer_id === c.peer_id && d.offline), m = o ? "offline" : c.status, u = o ? "r" : c.status === "working" ? "g" : c.status === "held" || c.status === "closing" ? "a" : "q", b = c.peer_id === i, l = c.peer_id === s;
    return /* @__PURE__ */ p(
      "li",
      {
        role: "option",
        "aria-selected": l,
        className: `hermes-peer-row${l ? " sel" : ""}${b ? " me" : ""}${o ? " off" : ""}`,
        onClick: () => t(c.peer_id),
        onDoubleClick: () => n(c),
        children: [
          /* @__PURE__ */ a("span", { className: `hermes-peer-dot dot ${u}` }),
          /* @__PURE__ */ p("span", { className: "hermes-peer-row-title", children: [
            c.name || c.agent_id.slice(0, 8),
            b ? /* @__PURE__ */ a("span", { className: "hermes-peer-you", children: "you" }) : null
          ] }),
          /* @__PURE__ */ p("span", { className: "hermes-peer-row-meta", children: [
            c.surface,
            " · ",
            m,
            c.current_activity ? ` · ${c.current_activity}` : ""
          ] })
        ]
      },
      c.agent_id
    );
  }) });
}
function D({ api: r, refresh: e }) {
  const [s, t] = y([]), [n, i] = y("");
  return v(() => {
    r.groups().then((o) => t(o.groups));
  }, [r, e]), /* @__PURE__ */ p("div", { children: [
    /* @__PURE__ */ p("div", { className: "hermes-peer-form", children: [
      /* @__PURE__ */ a("input", { value: n, placeholder: "Group name", onChange: (o) => i(o.target.value) }),
      /* @__PURE__ */ a("button", { onClick: () => {
        n.trim() && r.createGroup(n.trim()).then(() => i("")).then(() => r.groups()).then((o) => t(o.groups));
      }, children: "Create" })
    ] }),
    s.length ? null : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "No groups." }),
    /* @__PURE__ */ a("ul", { className: "hermes-peer-list", children: s.map((o) => /* @__PURE__ */ p("li", { className: "hermes-peer-row", children: [
      /* @__PURE__ */ a("span", { className: "hermes-peer-row-title", children: o.name }),
      /* @__PURE__ */ p("span", { className: "hermes-peer-row-meta", children: [
        o.members,
        " members"
      ] })
    ] }, o.group_id)) })
  ] });
}
function E({ api: r }) {
  const [e, s] = y([]);
  return v(() => {
    r.inbox().then((t) => s(t.messages));
  }, [r]), e.length ? /* @__PURE__ */ a("ul", { className: "hermes-peer-list", children: e.map((t) => /* @__PURE__ */ p("li", { className: "hermes-peer-row", children: [
    /* @__PURE__ */ p("span", { className: "hermes-peer-row-title", children: [
      "[",
      t.state,
      "]"
    ] }),
    /* @__PURE__ */ a("span", { className: "hermes-peer-row-meta", children: t.content.slice(0, 60) })
  ] }, t.message_id)) }) : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "Inbox empty." });
}
function I({
  requests: r
}) {
  return r.length ? /* @__PURE__ */ a("ul", { className: "hermes-peer-list", children: r.map((e) => /* @__PURE__ */ p("li", { className: "hermes-peer-row", children: [
    /* @__PURE__ */ p("span", { className: "hermes-peer-row-title", children: [
      "[",
      e.state,
      "]"
    ] }),
    /* @__PURE__ */ a("span", { className: "hermes-peer-row-meta", children: e.summary })
  ] }, e.request_id)) }) : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "No requests." });
}
function A({ ctx: r }) {
  const [e, s] = y(null);
  return v(() => {
    r.rest("/health").then((t) => s(t));
  }, [r]), e ? /* @__PURE__ */ p("div", { children: [
    /* @__PURE__ */ p("p", { className: "hermes-peer-row-title", children: [
      e.ok ? "Healthy" : "Unhealthy",
      " · backend ",
      e.backend
    ] }),
    e.problems.length ? null : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "No problems." }),
    /* @__PURE__ */ a("ul", { className: "hermes-peer-list", children: e.problems.map((t, n) => /* @__PURE__ */ p("li", { className: "hermes-peer-row", children: [
      /* @__PURE__ */ a("span", { className: "hermes-peer-row-title", children: t.problem }),
      /* @__PURE__ */ a("span", { className: "hermes-peer-row-meta", children: t.remedy })
    ] }, n)) })
  ] }) : /* @__PURE__ */ a("p", { className: "hermes-peer-muted", children: "Checking…" });
}
const G = {
  id: "hermes-peer",
  label: "Hermes Peer",
  activate(r) {
    var f, g;
    const e = P(r), s = [], t = r;
    let n = $(), i = n, c = !1, o = () => {
    };
    const m = q(e, (h) => {
      c || (n = h, i = h, o(h));
    });
    let u = null;
    o = (h) => {
      var N;
      u && (u.textContent = k(h), u.classList.toggle("hermes-peer-pill-off", (((N = h.summary) == null ? void 0 : N.offline_count) ?? 0) > 0));
    };
    const b = () => {
      typeof t.openWorkspace == "function" && t.openWorkspace("hermes-peer", {
        title: "Peers",
        // R2: read live state via stateRef so the panel updates after
        // refreshes instead of freezing on the captured object.
        render: () => _({ ctx: r, api: e, state: i, refresh: m })
      });
    };
    s.push(
      r.register({
        id: "peer-status",
        // H4: the host's STATUSBAR_AREAS uses exact-match keys
        // (statusBar.left/statusBar.right) — 'statusBar' rendered nowhere.
        area: "statusBar.left",
        title: "peer",
        order: 30,
        render: () => {
          const h = document.createElement("button");
          h.className = "hermes-peer-pill", h.textContent = k(n), h.title = "Peers — click for the expanded panel (Ctrl+P)", h.setAttribute("aria-label", "Peer sessions: open expanded panel");
          const N = new AbortController();
          return h.addEventListener("click", b, { signal: N.signal }), s.push(() => N.abort()), u = h, o(n), h;
        }
      })
    ), typeof t.openWorkspace == "function" && s.push(
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
      refresh: m
    });
    s.push(
      r.register({
        id: "peer-panel",
        area: "secondarySidebar",
        title: ((g = (f = r.i18n) == null ? void 0 : f.t) == null ? void 0 : g.call(f, "panel.title")) ?? "Peer",
        order: 30,
        render: l
      })
    );
    const d = e.onEvents(() => {
      m();
    });
    return s.push(d), m(), () => {
      c = !0;
      for (const h of s) h();
      u = null;
    };
  }
};
export {
  G as default
};
