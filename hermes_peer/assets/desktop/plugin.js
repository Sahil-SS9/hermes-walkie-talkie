import { jsxs as o, jsx as t } from "react/jsx-runtime";
import { useState as u, useEffect as N, useCallback as g } from "react";
function v(r) {
  return {
    health: () => r.rest("/health"),
    metrics: () => r.rest("/metrics"),
    peers: () => r.rest("/peers"),
    groups: () => r.rest("/groups"),
    createGroup: (e) => r.rest("/groups", { method: "POST", body: { name: e } }),
    groupMembers: (e) => r.rest(`/groups/${e}/members`),
    addMember: (e, n) => r.rest(`/groups/${e}/members`, { method: "POST", body: { agent_id: n } }),
    broadcastOutcomes: (e) => r.rest(`/broadcasts/${e}`),
    inbox: () => r.rest("/inbox"),
    requests: () => r.rest("/requests"),
    requestDetail: (e) => r.rest(`/requests/${e}`),
    respond: (e, n, s = "") => r.rest(`/requests/${e}/respond`, {
      method: "POST",
      body: { action: n, detail: s }
    }),
    onEvents: (e) => r.socket("/events", (n) => e(n))
  };
}
function f() {
  return { loading: !0, error: null, peers: [], requests: [], lastUpdated: null };
}
function w(r, e) {
  let n = 0;
  return async function() {
    const a = ++n;
    e({ ...f(), loading: !0 });
    try {
      const [l, c] = await Promise.all([r.peers(), r.requests()]);
      if (a !== n) return;
      e({
        loading: !1,
        error: null,
        peers: l.peers,
        requests: c.requests,
        lastUpdated: Date.now()
      });
    } catch (l) {
      if (a !== n) return;
      e({ ...f(), loading: !1, error: String(l) });
    }
  };
}
function q(r) {
  const { ctx: e, api: n, state: s, refresh: a } = r, [l, c] = u("peers"), [p, i] = u("default");
  return N(() => (a(), n.onEvents(() => void a())), [n, a, p]), g(
    (m) => {
      i(m), r.switchProfile(m);
    },
    [r]
  ), /* @__PURE__ */ o("div", { className: "hermes-peer-panel", children: [
    /* @__PURE__ */ t("div", { className: "hermes-peer-tabs", children: [
      ["peers", "Peers"],
      ["groups", "Groups"],
      ["inbox", "Inbox"],
      ["requests", "Requests"],
      ["health", "Health"]
    ].map(([m, d]) => /* @__PURE__ */ t(
      "button",
      {
        className: l === m ? "hermes-peer-tab active" : "hermes-peer-tab",
        onClick: () => c(m),
        children: d
      },
      m
    )) }),
    /* @__PURE__ */ o("div", { className: "hermes-peer-body", children: [
      s.loading ? /* @__PURE__ */ t("p", { className: "hermes-peer-muted", children: "Loading…" }) : null,
      s.error ? /* @__PURE__ */ t("p", { className: "hermes-peer-error", children: s.error }) : null,
      l === "peers" ? /* @__PURE__ */ t(P, { peers: s.peers }) : null,
      l === "groups" ? /* @__PURE__ */ t(y, { ctx: e, api: n, refresh: a }) : null,
      l === "inbox" ? /* @__PURE__ */ t(S, { api: n }) : null,
      l === "requests" ? /* @__PURE__ */ t(k, { api: n, requests: s.requests, refresh: a }) : null,
      l === "health" ? /* @__PURE__ */ t(C, { ctx: e }) : null
    ] })
  ] });
}
function P({ peers: r }) {
  return r.length ? /* @__PURE__ */ t("ul", { className: "hermes-peer-list", children: r.map((e) => /* @__PURE__ */ o("li", { className: "hermes-peer-row", children: [
    /* @__PURE__ */ t("span", { className: "hermes-peer-row-title", children: e.name || e.agent_id.slice(0, 8) }),
    /* @__PURE__ */ o("span", { className: "hermes-peer-row-meta", children: [
      e.surface,
      " · ",
      e.status
    ] })
  ] }, e.agent_id)) }) : /* @__PURE__ */ t("p", { className: "hermes-peer-muted", children: "No live peers." });
}
function y({ ctx: r, api: e, refresh: n }) {
  const [s, a] = u([]), [l, c] = u("");
  return N(() => {
    e.groups().then((i) => a(i.groups));
  }, [e, n]), /* @__PURE__ */ o("div", { children: [
    /* @__PURE__ */ o("div", { className: "hermes-peer-form", children: [
      /* @__PURE__ */ t("input", { value: l, placeholder: "Group name", onChange: (i) => c(i.target.value) }),
      /* @__PURE__ */ t("button", { onClick: () => {
        l.trim() && e.createGroup(l.trim()).then(() => c("")).then(() => e.groups()).then((i) => a(i.groups));
      }, children: "Create" })
    ] }),
    s.length ? null : /* @__PURE__ */ t("p", { className: "hermes-peer-muted", children: "No groups." }),
    /* @__PURE__ */ t("ul", { className: "hermes-peer-list", children: s.map((i) => /* @__PURE__ */ o("li", { className: "hermes-peer-row", children: [
      /* @__PURE__ */ t("span", { className: "hermes-peer-row-title", children: i.name }),
      /* @__PURE__ */ o("span", { className: "hermes-peer-row-meta", children: [
        i.members,
        " members"
      ] })
    ] }, i.group_id)) })
  ] });
}
function S({ api: r }) {
  const [e, n] = u([]);
  return N(() => {
    r.inbox().then((s) => n(s.messages));
  }, [r]), e.length ? /* @__PURE__ */ t("ul", { className: "hermes-peer-list", children: e.map((s) => /* @__PURE__ */ o("li", { className: "hermes-peer-row", children: [
    /* @__PURE__ */ o("span", { className: "hermes-peer-row-title", children: [
      "[",
      s.state,
      "]"
    ] }),
    /* @__PURE__ */ t("span", { className: "hermes-peer-row-meta", children: s.content.slice(0, 60) })
  ] }, s.message_id)) }) : /* @__PURE__ */ t("p", { className: "hermes-peer-muted", children: "Inbox empty." });
}
function k({
  api: r,
  requests: e,
  refresh: n
}) {
  return e.length ? /* @__PURE__ */ t("ul", { className: "hermes-peer-list", children: e.map((s) => /* @__PURE__ */ o("li", { className: "hermes-peer-row", children: [
    /* @__PURE__ */ o("span", { className: "hermes-peer-row-title", children: [
      "[",
      s.state,
      "]"
    ] }),
    /* @__PURE__ */ t("span", { className: "hermes-peer-row-meta", children: s.summary })
  ] }, s.request_id)) }) : /* @__PURE__ */ t("p", { className: "hermes-peer-muted", children: "No requests." });
}
function C({ ctx: r }) {
  const [e, n] = u(null);
  return N(() => {
    r.rest("/health").then((s) => n(s));
  }, [r]), e ? /* @__PURE__ */ o("div", { children: [
    /* @__PURE__ */ o("p", { className: "hermes-peer-row-title", children: [
      e.ok ? "Healthy" : "Unhealthy",
      " · backend ",
      e.backend
    ] }),
    e.problems.length ? null : /* @__PURE__ */ t("p", { className: "hermes-peer-muted", children: "No problems." }),
    /* @__PURE__ */ t("ul", { className: "hermes-peer-list", children: e.problems.map((s, a) => /* @__PURE__ */ o("li", { className: "hermes-peer-row", children: [
      /* @__PURE__ */ t("span", { className: "hermes-peer-row-title", children: s.problem }),
      /* @__PURE__ */ t("span", { className: "hermes-peer-row-meta", children: s.remedy })
    ] }, a)) })
  ] }) : /* @__PURE__ */ t("p", { className: "hermes-peer-muted", children: "Checking…" });
}
const E = {
  id: "hermes-peer",
  label: "Hermes Peer",
  activate(r) {
    var m, d;
    const e = v(r), n = [];
    let s = "default", a = f(), l = () => {
    };
    const c = w(e, (h) => {
      a = h, l(h);
    }), p = (h) => {
      h !== s && (s = h, a = f(), c());
    };
    n.push(
      r.register({
        id: "peer-status",
        area: "statusBar",
        title: "peer",
        order: 30
      })
    );
    const i = () => q({
      ctx: r,
      api: e,
      state: a,
      refresh: c,
      switchProfile: p
    });
    n.push(
      r.register({
        id: "peer-panel",
        area: "secondarySidebar",
        title: ((d = (m = r.i18n) == null ? void 0 : m.t) == null ? void 0 : d.call(m, "panel.title")) ?? "Peer",
        order: 30,
        render: i
      })
    );
    const b = e.onEvents(() => {
      c();
    });
    return n.push(b), c(), () => {
      for (const h of n) h();
    };
  }
};
export {
  E as default
};
