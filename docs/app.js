"use strict";
const $ = (id) => document.getElementById(id);
const roles = {
  foundation: "기초 읽기 후보",
  development: "접근 확장",
  benchmark: "평가·벤치마크",
  counterpoint: "반례·한계 검토",
  recent: "최근 검토 후보",
};
const colors = [
  "#087e86",
  "#b16f54",
  "#638653",
  "#7063a0",
  "#3e7aa0",
  "#b08d39",
  "#aa6786",
  "#587c7f",
];
const text = (tag, value, cls) => {
  const el = document.createElement(tag);
  el.textContent = value;
  if (cls) el.className = cls;
  return el;
};
const safeLink = (label, url, cls) => {
  const a = text("a", label, cls);
  if (/^https:\/\//.test(url)) {
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  }
  return a;
};
let data,
  network,
  visible = [],
  selected = null;
const paperById = new Map();
const citationLabel = (p) =>
  p.citations == null
    ? "인용 수 미조회"
    : `인용 ${p.citations.toLocaleString()}회 · ${p.citation_observed_at} · OpenAlex`;
function tooltip(p) {
  const box = document.createElement("div");
  box.append(
    safeLink(p.title, p.url),
    text("span", `${p.year} · ${p.venue || "학회 미검증"}`),
    text("span", citationLabel(p)),
    text("span", `서지: ${p.metadata_status} / 검토: ${p.review_status}`),
  );
  return box;
}
function updateSubtopics() {
  const current = $("subtopic").value;
  $("subtopic").replaceChildren(new Option("전체 소분류", ""));
  for (const t of data.topics) {
    if ($("topic").value && t.id !== $("topic").value) continue;
    for (const s of t.subtopics)
      $("subtopic").add(new Option(`${t.label} / ${s.label}`, s.id));
  }
  $("subtopic").value = [...$("subtopic").options].some(
    (o) => o.value === current,
  )
    ? current
    : "";
}
function filtered() {
  const query = $("query").value.toLowerCase().trim(),
    tid = $("topic").value,
    sid = $("subtopic").value,
    role = $("role").value;
  return data.papers
    .filter(
      (p) =>
        (!tid || p.subtopics.some((s) => s.startsWith(tid + "."))) &&
        (!sid || p.subtopics.includes(sid)) &&
        (!role || p.role === role) &&
        p.year >= Number($("from-year").value) &&
        p.year <= Number($("to-year").value) &&
        (!query ||
          [p.title, p.abstract, ...(p.authors || [])]
            .join(" ")
            .toLowerCase()
            .includes(query)),
    )
    .sort((a, b) => {
      if ($("sort").value === "year")
        return b.year - a.year || a.title.localeCompare(b.title);
      if ($("sort").value === "citations")
        return (b.citations ?? -1) - (a.citations ?? -1) || b.year - a.year;
      return (
        (a.role === "foundation" ? 0 : 1) - (b.role === "foundation" ? 0 : 1) ||
        a.year - b.year ||
        a.title.localeCompare(b.title)
      );
    });
}
function showPaper(id) {
  const p = paperById.get(id);
  if (!p) return;
  selected = id;
  const d = $("details");
  d.replaceChildren(
    text("p", "PAPER DETAILS", "eyebrow"),
    text("span", roles[p.role] || p.role, "badge"),
    text("h2", p.title),
    text("p", `${p.year} · ${p.venue || "게재 학회 미검증"}`),
    safeLink("논문 열기 ↗", p.url),
    text("p", citationLabel(p)),
    text("p", `서지: ${p.metadata_status} · 독해: ${p.review_status}`),
    text("p", p.notes),
  );
  if (p.authors?.length)
    d.append(text("h3", "저자"), text("p", p.authors.join(", ")));
  d.append(
    text("h3", "보고된 주장·결과: 출처의 초록"),
    text(
      "p",
      p.abstract || "초록과 실험 결과를 독립 검토하지 않은 서지 후보입니다.",
      "abstract",
    ),
  );
  for (const t of data.topics)
    for (const s of t.subtopics)
      if (p.subtopics.includes(s.id)) {
        d.append(
          text("h3", s.label),
          text("p", `검증할 가설: ${s.question}`),
          text("p", `검토할 공백·실험: ${s.review_gap}`),
        );
      }
  d.append(text("h3", "확인한 출처"));
  for (const s of p.sources)
    d.append(safeLink(`${s.kind} · ${s.retrieved_at} ↗`, s.url, "source"));
  const edges = data.edges.filter((e) => e.from === id || e.to === id);
  d.append(
    text("h3", "근거가 있는 논문 관계"),
    text(
      "p",
      edges.length
        ? `${edges.length}개 관계. 직접 인용은 주장에 대한 지지를 의미하지 않습니다.`
        : "확인된 관계가 없습니다. 관계가 없다는 증거는 아닙니다.",
    ),
  );
  for (const e of edges) {
    const other = paperById.get(e.from === id ? e.to : e.from);
    const b = text(
      "button",
      `${e.relation}: ${other?.title || "논문"}`,
      "paper-card",
    );
    b.onclick = () => showPaper(other.id);
    d.append(b, text("p", e.evidence), safeLink("관계 근거 ↗", e.source));
  }
  for (const b of $("papers").querySelectorAll("button"))
    b.setAttribute("aria-pressed", String(b.dataset.paperId === id));
}
function draw() {
  visible = filtered();
  const ids = new Set(visible.map((p) => p.id));
  $("result-count").textContent =
    `${visible.length}편 / 전체 ${data.papers.length}편`;
  $("map-title").textContent = $("topic").value
    ? data.topics.find((t) => t.id === $("topic").value).label
    : "전체 연구 지도";
  $("papers").replaceChildren();
  for (const p of visible) {
    const b = text("button", "", "paper-card");
    b.dataset.paperId = p.id;
    b.setAttribute("aria-pressed", String(p.id === selected));
    b.append(
      text("span", roles[p.role] || p.role, "badge"),
      text("strong", p.title),
      text(
        "small",
        `${p.year} · ${p.venue || "학회 미검증"} · ${citationLabel(p)}`,
      ),
    );
    b.onclick = () => {
      if (!$("topic").value) {
        $("topic").value = p.subtopics[0].split(".")[0];
        updateSubtopics();
        draw();
      }
      showPaper(p.id);
      network.selectNodes(["paper:" + p.id]);
    };
    $("papers").append(b);
  }
  if (!visible.length)
    $("papers").append(
      text("p", "조건에 맞는 논문이 없습니다. 필터를 조정하세요.", "muted"),
    );
  const nodes = [],
    edges = [];
  const citationsOnly = $("view").value === "citations";
  const expanded = Boolean(
    citationsOnly ||
      $("topic").value ||
      $("subtopic").value ||
      $("query").value.trim() ||
      $("role").value,
  );
  if (!citationsOnly && visible.length) {
    nodes.push({
      id: "root",
      label: "인간과 AI",
      level: 0,
      shape: "box",
      color: "#1d333b",
      font: { color: "#fff" },
    });
    for (const [i, t] of data.topics.entries()) {
      const subs = t.subtopics.filter((s) =>
        visible.some((p) => p.subtopics.includes(s.id)),
      );
      if (!subs.length) continue;
      nodes.push({
        id: t.id,
        label: t.label,
        level: 1,
        shape: "box",
        color: colors[i],
        font: { color: "#fff" },
      });
      edges.push({ from: "root", to: t.id, color: "#bdcfc3" });
      if (!expanded) continue;
      for (const s of subs) {
        nodes.push({
          id: s.id,
          label: s.label,
          level: 2,
          shape: "box",
          color: "#edf3ed",
          title: s.question,
        });
        edges.push({ from: t.id, to: s.id, color: "#bdcfc3" });
        for (const p of visible)
          if (p.subtopics.includes(s.id))
            edges.push({ from: s.id, to: "paper:" + p.id, color: "#cfdbd2" });
      }
    }
  }
  if (expanded)
    for (const p of visible) {
      const primary = data.topics.findIndex((t) =>
        p.subtopics.some((s) => s.startsWith(t.id + ".")),
      );
      nodes.push({
        id: "paper:" + p.id,
        label: `${p.title.length > 39 ? p.title.slice(0, 38) + "…" : p.title}\n${p.year}`,
        level: 3,
        shape: p.role === "foundation" ? "diamond" : "dot",
        size: p.role === "foundation" ? 11 : 7,
        color: colors[Math.max(0, primary)],
        title: tooltip(p),
        font: { size: 10, color: "#30434b" },
      });
    }
  const relationEdges = data.edges.filter(
    (e) => ids.has(e.from) && ids.has(e.to),
  );
  if (citationsOnly)
    for (const e of relationEdges)
      edges.push({
        from: "paper:" + e.from,
        to: "paper:" + e.to,
        arrows: "to",
        title: `${e.relation}: ${e.evidence}`,
        color: e.relation === "cites" ? "#087e86" : "#b57c36",
        dashes: e.relation !== "cites",
      });
  $("graph-status").textContent = citationsOnly
    ? `근거가 있는 관계 ${relationEdges.length}개. 선은 인용·확장·반론 유형에 따라 표시됩니다. ${relationEdges.length ? "" : "현재 API 접근 차단으로 인용 관계가 미수집 상태입니다."}`
    : expanded
      ? "선은 주제 포함 관계입니다. 논문 간 인용이나 후속 연구 관계를 의미하지 않습니다."
      : "대분류를 선택하면 세부 주제와 논문이 펼쳐집니다. 아래 읽기 목록에서도 논문을 선택할 수 있습니다.";
  if (network) network.destroy();
  network = new vis.Network(
    $("graph"),
    { nodes, edges },
    {
      layout: {
        hierarchical: citationsOnly
          ? false
          : {
              enabled: true,
              direction: "LR",
              levelSeparation: 190,
              nodeSpacing: 55,
              treeSpacing: 75,
              sortMethod: "directed",
            },
      },
      physics: citationsOnly ? { stabilization: { iterations: 150 } } : false,
      interaction: {
        hover: true,
        tooltipDelay: 180,
        keyboard: { enabled: true, bindToWindow: false },
      },
      nodes: {
        borderWidth: 1,
        font: { face: "system-ui", size: 12 },
        margin: 10,
      },
      edges: { smooth: false, width: 0.8 },
    },
  );
  network.on("click", (p) => {
    const id = p.nodes[0];
    if (id?.startsWith("paper:")) showPaper(id.slice(6));
    else if (data.topics.some((t) => t.id === id)) {
      $("topic").value = id;
      updateSubtopics();
      draw();
    } else if (typeof id === "string" && id.includes(".")) {
      $("topic").value = id.split(".")[0];
      updateSubtopics();
      $("subtopic").value = id;
      draw();
    }
  });
  network.fit();
  if (selected && !ids.has(selected)) {
    selected = null;
    $("details").replaceChildren(
      text("p", "PAPER DETAILS", "eyebrow"),
      text("h2", "논문 상세 정보"),
      text("p", "선택한 논문이 현재 필터에서 제외되었습니다."),
    );
  }
}
async function init() {
  try {
    const embedded = $("research-map-data");
    if (embedded) {
      data = JSON.parse(embedded.textContent);
    } else {
      const appScript = [...document.scripts].find((s) =>
        new URL(s.src || document.baseURI).pathname.endsWith("/app.js"),
      );
      const url = new URL("data/map.json", appScript?.src || document.baseURI);
      const res = await fetch(url);
      if (!res.ok) throw Error(`지도 데이터 HTTP ${res.status}`);
      data = await res.json();
    }
    for (const p of data.papers) paperById.set(p.id, p);
    for (const t of data.topics) $("topic").add(new Option(t.label, t.id));
    $("from-year").value = Math.min(...data.papers.map((p) => p.year));
    $("to-year").value = Math.max(...data.papers.map((p) => p.year));
    $("stats").replaceChildren(
      ...[
        [data.topics.length, "연구 분야"],
        [data.topics.reduce((n, t) => n + t.subtopics.length, 0), "세부 주제"],
        [data.papers.length, "읽기 후보"],
      ].map(([n, l]) => {
        const e = document.createElement("div");
        e.append(text("strong", n), text("span", l));
        return e;
      }),
    );
    $("as-of").textContent = data.as_of;
    updateSubtopics();
    for (const id of [
      "query",
      "subtopic",
      "role",
      "sort",
      "from-year",
      "to-year",
      "view",
    ])
      $(id).addEventListener(id === "query" ? "input" : "change", draw);
    $("topic").onchange = () => {
      updateSubtopics();
      draw();
    };
    $("fit").onclick = () => network.fit({ animation: true });
    $("reset").onclick = () => {
      for (const id of ["query", "topic", "role", "subtopic"]) $(id).value = "";
      $("sort").value = "reading";
      $("from-year").value = Math.min(...data.papers.map((p) => p.year));
      $("to-year").value = Math.max(...data.papers.map((p) => p.year));
      updateSubtopics();
      draw();
    };
    draw();
  } catch (e) {
    $("stats").textContent = "지도 로딩 오류";
    console.error("Research map initialization failed:", e);
    $("graph").replaceChildren(
      text(
        "p",
        "지도를 불러오지 못했습니다. 페이지를 새로고침해 주세요.",
        "error",
      ),
    );
  }
}
init();
