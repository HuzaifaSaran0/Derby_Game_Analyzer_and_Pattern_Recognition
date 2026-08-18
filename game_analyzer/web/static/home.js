(function () {
  const list = document.querySelector("[data-game-list]");
  const empty = document.querySelector("[data-empty-games]");
  const live = window.gameAnalyzerLive;
  if (!list || !live) return;

  let last = "";

  function titleCase(value) {
    if (!value) return "";
    return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
  }

  function render(games) {
    empty.hidden = games.length > 0;
    list.innerHTML = games
      .map(function (g) {
        const winner = g.winner_suit
          ? '<span class="winner has">' + titleCase(g.winner_suit) + " wins</span>"
          : '<span class="winner">In play</span>';
        const shots = g.shot_count + " shot" + (g.shot_count === 1 ? "" : "s");
        return (
          '<li><a class="game-card" href="/game/' +
          g.game_id +
          '"><div class="game-id">' +
          g.game_id +
          '</div><div class="game-meta">' +
          winner +
          "<span>" +
          shots +
          '</span></div><div class="when">' +
          (g.started_at || "") +
          "</div></a></li>"
        );
      })
      .join("");
  }

  live.start(async function () {
    try {
      const data = await live.get("/games.json");
      const games = data.games || [];
      const sig = JSON.stringify(games);
      live.stamp(true, games.length + " game" + (games.length === 1 ? "" : "s"));
      if (sig === last) return;
      last = sig;
      render(games);
    } catch (_err) {
      live.stamp(false);
    }
  });
})();
