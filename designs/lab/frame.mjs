import { DEMOS, stageHTML, ringHTML, playDemo } from "./animations.mjs";

const params = new URLSearchParams(location.search);
const demo = DEMOS.find((item) => item.id === params.get("moment"));
const option = params.get("option");
document.documentElement.dataset.theme =
  params.get("theme") === "dark" ? "dark" : "light";
const notify = (state) =>
  parent.postMessage(
    { source: "ibflip-motion-preview", state },
    location.origin,
  );
if (!demo || !demo.options[option]) {
  notify("error");
} else {
  const target = document.getElementById("preview");
  target.innerHTML = demo.ring ? ringHTML() : stageHTML();
  if (params.get("play") === "1") {
    notify("playing");
    try {
      await playDemo(demo.id, option, target);
      notify("finished");
    } catch (_) {
      notify("error");
    }
  } else {
    notify("ready");
  }
}
