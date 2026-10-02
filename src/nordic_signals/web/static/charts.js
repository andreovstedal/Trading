// Crosshair and tooltip for the charts drawn by web/charts.py (div.chart with data-points). live.js calls
// pfCharts.init again for the parts of the page it swaps in.
window.pfCharts = {
  init(root = document) {
    root.querySelectorAll(".chart[data-points]").forEach((chart) => {
      if (chart.dataset.bound) return;
      chart.dataset.bound = "1";
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
        // Keep the tooltip inside the chart; it scrolls with a chart that is wider than the screen.
        const half = tip.offsetWidth / 2;
        const left = Math.min(Math.max(nearest.x * scale, half), Math.max(box.width - half, half));
        tip.style.left = `${left}px`;
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
      // A chart wider than a phone scrolls; start at the newest end.
      if (chart.scrollWidth > chart.clientWidth) chart.scrollLeft = chart.scrollWidth;
    });
  },
};
window.pfCharts.init();
