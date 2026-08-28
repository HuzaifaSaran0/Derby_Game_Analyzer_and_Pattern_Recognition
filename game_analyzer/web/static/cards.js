window.gameAnalyzerCards = {
  miniCard(card) {
    if (!card) return "";
    const rank = card.rank || "?";
    const color = card.color || "#888";
    const symbol = card.symbol || "?";
    return (
      '<div class="mini-card" style="color:' +
      color +
      '" title="' +
      (card.code || "") +
      '"><span class="rank">' +
      rank +
      '</span><span class="pip">' +
      symbol +
      "</span></div>"
    );
  },

  miniCards(cards) {
    if (!cards || !cards.length) return '<span class="dash">—</span>';
    return cards.map((c) => this.miniCard(c)).join("");
  },

  suitTable(rows) {
    if (!rows || !rows.length) {
      return '<p class="empty">No cards stored.</p>';
    }
    return (
      '<div class="suit-table">' +
      rows
        .map(
          (row) =>
            '<div class="suit-row"><div class="suit-name" style="color:' +
            row.color +
            '">' +
            row.symbol +
            " " +
            row.name +
            '</div><div class="mini-cards">' +
            this.miniCards(row.cards) +
            "</div></div>"
        )
        .join("") +
      "</div>"
    );
  },

  matchedRoundsBlock(rounds) {
    if (!rounds || !rounds.length) return "";
    return rounds
      .map(function (row) {
        const label = row.label || "Round " + row.round_n + " draw cards";
        return (
          '<div class="game-card-section"><strong>' +
          label +
          "</strong>" +
          '<div class="mini-cards matched-round-cards">' +
          window.gameAnalyzerCards.miniCards(row.cards) +
          "</div></div>"
        );
      })
      .join("");
  },

  gameCardBlock(game) {
    const winner = game.winner || "—";
    const src = game.draw_source || "unknown";
    let srcLabel = src;
    let srcCls = "draw-src";
    if (game.frame_verified) {
      srcLabel = "frames ✓";
      srcCls = "draw-src is-verified";
    } else if (src === "json") {
      srcLabel = "draws json";
      srcCls = "draw-src is-fallback";
    } else if (src === "guess") {
      srcLabel = "guess draws";
      srcCls = "draw-src is-fallback";
    } else if (src === "table") {
      srcLabel = "suit table";
      srcCls = "draw-src is-weak";
    } else if (src === "frames") {
      srcLabel = "frames";
      srcCls = "draw-src is-verified";
    }
    let html =
      '<div class="game-card-block"><div class="game-card-head">#' +
      game.game_id +
      " → " +
      winner +
      ' <span class="' +
      srcCls +
      '">' +
      srcLabel +
      "</span></div><div class=\"game-card-section\"><strong>Handicap</strong>" +
      this.suitTable(game.handicap) +
      "</div>";
    if (game.draw_rounds && game.draw_rounds.length) {
      html += this.matchedRoundsBlock(game.draw_rounds);
    } else if (game.matched_rounds && game.matched_rounds.length) {
      html += this.matchedRoundsBlock(game.matched_rounds);
    } else {
      html +=
        '<div class="game-card-section"><strong>Draws (' +
        (game.draw_count || 0) +
        " cards · " +
        (game.draw_rounds || 0) +
        " rounds)</strong>" +
        this.suitTable(game.draws) +
        "</div>";
    }
    html += "</div>";
    return html;
  },

  winChance(rows, note) {
    if (!rows || !rows.length) {
      return '<p class="empty">Handicap not visible yet.</p>';
    }
    let html = rows
      .map(function (row) {
        const cls =
          "win-row" +
          (row.highlight ? " highlight" : "") +
          (row.preview ? " preview" : "");
        return (
          '<div class="' +
          cls +
          '"><span class="win-suit" style="color:' +
          row.color +
          '">' +
          row.symbol +
          " " +
          row.suit +
          '</span><span class="win-text">' +
          row.text +
          "</span></div>"
        );
      })
      .join("");
    if (note) html += '<p class="win-note">' + note + "</p>";
    return html;
  },
};
