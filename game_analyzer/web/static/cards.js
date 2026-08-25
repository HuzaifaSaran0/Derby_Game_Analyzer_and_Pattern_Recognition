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

  gameCardBlock(game) {
    const winner = game.winner || "—";
    let html =
      '<div class="game-card-block"><div class="game-card-head">#' +
      game.game_id +
      " → " +
      winner +
      '</div><div class="game-card-section"><strong>Handicap</strong>' +
      this.suitTable(game.handicap) +
      '</div><div class="game-card-section"><strong>Draws (' +
      (game.draw_count || 0) +
      " cards · " +
      (game.draw_rounds || 0) +
      " rounds)</strong>" +
      this.suitTable(game.draws) +
      "</div></div>";
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
