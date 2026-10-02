// Crosshair and tooltip for line charts drawn by web/charts.py (div.chart with data-points).
document.querySelectorAll(".chart[data-points]").forEach((chart) => {
  const points = JSON.parse(chart.dataset.points);
  const svg = chart.querySelector("svg");
  const cross = svg.querySelector(".cross");
  const dot = svg.querySelector(".dot.hover");
  const tip = chart.querySelector(".tip");
  const viewWidth = svg.viewBox.baseVal.width;

  const show = (event) => {
    const box = svg.getBoundingClientRect();
    const scale = box.width / viewWidth;
    const x = (event.clientX - box.left) / scale;
    let nearest = points[0];
    for (const p of points) if (Math.abs(p.x - x) < Math.abs(nearest.x - x)) nearest = p;
    cross.setAttribute("x1", nearest.x);
    cross.setAttribute("x2", nearest.x);
    dot.setAttribute("cx", nearest.x);
    dot.setAttribute("cy", nearest.y);
    cross.setAttribute("visibility", "visible");
    dot.setAttribute("visibility", "visible");
    tip.textContent = nearest.t;
    tip.hidden = false;
    tip.style.left = `${nearest.x * scale}px`;  // the tooltip scrolls with the chart
    tip.style.top = `${nearest.y * scale}px`;
  };
  const hide = () => {
    cross.setAttribute("visibility", "hidden");
    dot.setAttribute("visibility", "hidden");
    tip.hidden = true;
  };
  svg.addEventListener("pointermove", show);
  svg.addEventListener("pointerdown", show);
  svg.addEventListener("pointerleave", hide);
});
