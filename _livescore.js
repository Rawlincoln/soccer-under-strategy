"use strict";
var refreshTime = 1; // 
var blinkPause = 500; // ms
var blinkCount = 20; // changes on/off for a single blink
var oldMatchesHours = 18; // time range for which matches are displayed
var newMatchesHours = 12;


var sounds = {};
var firstTabLoad = true;
var trackedStats = ["score_A", "score_B", "red_A", "red_B", "match_period"];
var soundAlerts = {goals: false, canceled: false, pauseend: false, redcards: false, yellowcards: false};
var prev_tabMatches = {};
var ajxTimer = null;
var area_id = 0;
var reqCnt = 0;
var reqTs = 0;
var reqRcv = 0;
var blinkRows = {};
var blinkOn = false;
var crfavoriteMatches = {};
var lastData = null;
var tracked_matches = {};
var viewNeedsRebuild = true;
var recalculateTabs = true;
var scoreBarNeedsRebuild = true;
var matchTimestampMin = 0;
var matchTimestampMax = 0;
var TAB_ALL_GAMES = 0;
var TAB_LIVE_GAMES = 1;
var TAB_FINISHED = 2;
var TAB_SCHEDULED = 3;
var TAB_FAVORITES = 4;
var crTab = TAB_LIVE_GAMES;
var tabFilters = {};
var matchesToRequest = [];
var testDataHook = null;
var CARD_NAMES = {'yellowcard': 'yellow cards', 'yellowred': 'second yellow cards', 'redcard': 'red cards'};
var streamed_matches = {};
var dbg_stop = false;

tabFilters[TAB_ALL_GAMES] = function (match) {
    return isStandardStatusType(match.status);
};
tabFilters[TAB_LIVE_GAMES] = function (match) {
    return isPlayingStatusType(match.status);
};
tabFilters[TAB_FINISHED] = function (match) {
    return isPlayedStatusType(match.status);
};
tabFilters[TAB_SCHEDULED] = function (match) {
    return isFixtureStatusType(match.status);
};
// Favorites
tabFilters[TAB_FAVORITES] = function (match) {
    return match.isFav == '1' && isStandardStatusType(match.status);
};

function isSmallWindow() {
    return window.matchMedia("(max-width: 767px)").matches;
}

var renderSmallWindow = isSmallWindow();


window.addEventListener("unhandledrejection", (event) => {
    $("#livescore_js_trace").append(`UNHANDLED PROMISE REJECTION: ${event.reason}<br>`);
    console.log(event);
});
onerror = (message, source, lineno, colno, error) => {
    $("#livescore_js_trace").append(`ONERROR: ${message}, ${source}, ${lineno}, ${colno}, ${error}<br>`);
    console.log(message, source, lineno, colno, error);    
}

$(function(){
    $("body").delegate('img', 'error', function (e) {
        $("#livescore_js_trace").append(`IMG ERROR: ${e}<br>`);
        console.log(e);
    });
});


function isStandardStatusType(status) {
    return isFixtureStatusType(status) || isPlayingStatusType(status) || isPlayedStatusType(status);
}

function isFixtureStatusType(status) {
    return status === 'NS' || status === 'TBA';
}
function isPlayingStatusType(status) {
    return status === 'LIVE' ||
            status === 'HT' ||
            status === 'ET' ||
            status === 'PEN_LIVE' ||
            status === 'BREAK';
}

function isPlayedStatusType(status) {
    return status === 'FT' ||
            status === 'AET' ||
            status === 'FT_PEN';
}

function calculateMatchTimestampRange() {
    var crTs = Date.now() / 1000;
    matchTimestampMin = crTs - oldMatchesHours * 60 * 60;
    matchTimestampMax = crTs + newMatchesHours * 60 * 60;
}

function addMatch(match) {
    var match_id = match.match_id;
    var expanded = false;
    var displayed = false;
    if (match_id in tracked_matches) {
        expanded = tracked_matches[match_id].expanded;
        displayed = tracked_matches[match_id].displayed;
    }
    var snap;
    if (displayed) {
        snap = takeAlertSnapshot(tracked_matches[match_id]);
    }
    match['expanded'] = expanded;
    match['displayed'] = displayed;
    match.timestamp = parseInt(match.timestamp); // used for checking if it is in range
    tracked_matches[match_id] = match;
    if (displayed) {
        viewNeedsRebuild = true;
        checkForAlerts(match, snap);
    }
    if (!isFixtureStatusType(match.status)) {
        scoreBarNeedsRebuild = true;
    }
    match.events.sort(sortByMinute);
    match['streamed'] = (match.sp_match_id in streamed_matches);
}

function addStats(stats) {
    var match_id = stats.match_id;
    if (!(match_id in tracked_matches)) {
        matchesToRequest.push(match_id);
        return;
    }
    var match = tracked_matches[match_id];
    var displayed = match.displayed;
    var snap;
    if (displayed) {
        snap = takeAlertSnapshot(match);
    }
    $.extend(match, stats);
    if (displayed) {
        viewNeedsRebuild = true;
        checkForAlerts(match, snap);
    } else {
        evaluateMatchVisibility(match_id); // match started?
    }
    if (!isFixtureStatusType(match.status)) {
        scoreBarNeedsRebuild = true;
    }

}
function addMinute(minute_stats) {
    var match_id = minute_stats.match_id;
    if (!(match_id in tracked_matches)) {
        matchesToRequest.push(match_id);
        return;
    }
    var match = tracked_matches[match_id];
    $.extend(match, minute_stats);
    if (match.displayed && !viewNeedsRebuild) {
        var td = $(".matchRow[data-match=" + match_id + "] .match_period_td");
        setMatchTime(td, match);
    }
}

function addMatchEvent(event) {
    var match_id = event.match_id;
    if (!(match_id in tracked_matches)) {
        matchesToRequest.push(match_id);
        return;
    }
    var match = tracked_matches[match_id];
    var displayed = match.displayed;
    var snap;
    if (displayed) {
        snap = takeAlertSnapshot(match);
    }
    var events = match.events;
    var nEvents = events.length;
    var newEventIdx = -1;
    for (var i = 0; i < nEvents; i++) {
        if (events[i].id == event.id) {
            newEventIdx = i;
            events[i] = event;
            break;
        }
    }
    if (newEventIdx == -1) {
        // new event
        events.push(event);
        newEventIdx = nEvents;
    }
    if (displayed) {
        checkForAlerts(match, snap);
        // expanded or cards
        if (match.expanded || event.type_id == '19' || event.type_id == '20' || event.type_id == '21') {
            viewNeedsRebuild = true;
        }
    }
    match.events.sort(sortByMinute);
}

function evaluateMatchVisibility(match_id) {
    if (!match_id in tracked_matches)
        return false;
    var match = tracked_matches[match_id];
    var was_displayed = match.displayed;
    var should_be_displayed = true;
    // check if it is too old
    if (match.timestamp < matchTimestampMin) {
        delete tracked_matches[match_id];
        should_be_displayed = false;
    } else if ((match.timestamp > matchTimestampMax)
            || (area_id != 0 && area_id != match.area_id)
            || !(tabFilters[crTab](match))
            || (!match.lsConfirmed && match.timestamp < Date.now() + 9 * 60 * 1000))
    {
        should_be_displayed = false;
    }
    if (was_displayed !== should_be_displayed) {
        viewNeedsRebuild = true;
    }
    match.displayed = should_be_displayed;
    return match.displayed;
}

function sortByKickOff(a, b) {
    // reverse order of kickoff
    if (a.timestamp < b.timestamp) {
        return 1;
    }
    if (a.timestamp > b.timestamp) {
        return -1;
    }
    return sortByCompetitions(a, b);
}

function sortByCompetitions(a, b) {
    var a_area = sm_areas[a.area_id];
    var b_area = sm_areas[b.area_id];
    if (a_area < b_area) {
        return -1;
    }
    if (a_area > b_area) {
        return 1;
    }

    if (a.leagueName < b.leagueName) {
        return -1;
    }
    if (a.leagueName > b.leagueName) {
        return 1;
    }
    // fallback
    if (a.timestamp < b.timestamp) {
        return 1;
    }
    if (a.timestamp > b.timestamp) {
        return -1;
    }
    if (a.ta_name < b.ta_name) {
        return -1;
    }
    if (a.ta_name > b.ta_name) {
        return 1;
    }
    return 0;
}

/**
 * 
 * @param a
 * @param b
 * @returns int cmp
 */
function sortByMinute(a, b) {
    if (a.minute < b.minute) {
        return -1;
    }
    if (a.minute > b.minute) {
        return 1;
    }
    if (a.extra_minute < b.extra_minute) {
        return -1;
    }
    if (a.extra_minute > b.extra_minute) {
        return 1;
    }
    return a.id - b.id;
}

function rebuildView() {
    var view_matches = [];
    for (var match_id in tracked_matches) {
        if (tracked_matches.hasOwnProperty(match_id)) {
            if (evaluateMatchVisibility(match_id)) {
                view_matches.push(tracked_matches[match_id]);
            }
        }
    }

    if (view_matches.length === 0) {
        $("#livescore_matches").html('<span>No matches in this section!</span>');
    } else {
        renderSmallWindow = isSmallWindow();
        if (renderSmallWindow) {
            buildMatchesCompact(view_matches);
        } else {
            buildMatchesTable(view_matches);
        }
    }
    recalculateTabCount();
    viewNeedsRebuild = false;
}

function buildMatchesCompact(view_matches) {
    view_matches.sort(sort_mode == 1 ? sortByKickOff : sortByCompetitions);
    var crSeasonId = 0;
    var crSection = -1;
    var seFavCheck = null;
    var n = view_matches.length;
    var table = $('<div class="lsmMatchesCompact"></div>');
    var allMatchRows = [];
    for (var i = 0; i < n; i++) {
        var match = view_matches[i];
        if (crSeasonId != match.season_id) {
            crSeasonId = match.season_id;
            crSection++;
            var seasonRow = $('<div class="lsmSeasonRow" data-section="' + crSection + '"></div>');
            var area_name = sm_areas[match.area_id];
            var link = $('<a target="_blank" class="seasonLink" href="/goto.php?t=s&match_id=' + match.match_id + '"></a>');
            link.attr('title', area_name);
            link.text(area_name + ' - ' + match.leagueName);
            link.prepend('&nbsp;');
            link.prepend(getFlag(match.area_id));
            seFavCheck = $('<input type="checkbox" class="seFavCheck" checked="checked">');
            /* seasonRow.append(seFavCheck); */
            seasonRow.append(link);
            seasonRow.append('<a class="topPageLink" href="#topPage">Top&#x25B2;</a>');
            table.append(seasonRow);
        }
        if (!match.isFav) {
            seFavCheck.prop('checked', false);
        }
        var matchRow = generateMatchRowCompact(match, crSection, false);
        allMatchRows.push(matchRow);
        table.append(matchRow);
        if (match.expanded) {
            table.append(generateLsmExpanded(match));
        }
    }
    zebraRows(allMatchRows);
    $("#livescore_matches").html(table);
}
function generateLsmExpanded(match) {
    var main = $('<div class="lsmExpanded" data-match="' + match.match_id + '"></div>');
    main.append(generateLsmMatchButtons(match));
    var eventRows = generateMatchEventRowsCompact(match);
    var nEvents = eventRows.length;
    for (var ie = 0; ie < nEvents; ie++) {
        var eventRow = eventRows[ie];
        main.append(eventRow);
    }
    return main;
}
function generateLsmMatchButtons(match) {
    var match_id = match.match_id;
    var match_name = match.ta_name + ' vs ' + match.tb_name;
    var row = $('<div class="lsmMatchButtons"></div>');

    var td;
    // Bet button
    if (isFixtureStatusType(match.status) || isPlayingStatusType(match.status)) {
        var link = $('<a target="_blank" href="/goto.php?t=b&match_id=' + match_id + '" class="navBet">Play</a>');
        link.attr('title', 'Bet Now on ' + match_name + ' !');
        if (isPlayingStatusType(match.status)) {
            link.addClass('inplay_bet');
        }
        td = $('<div class="nOutcomesArea" align="right"></div>');
        td.append(link);
        row.append(td);
    } else {
        row.append('<div></div>');
    }

    // Match button
    {
        var link = $('<a target="_blank" href="/goto.php?t=m&match_id=' + match_id + '" class="smallDetails"><img src="/images/matchstats-icon2.png"></a>');
        link.attr('title', 'Match Stats for ' + match_name);
        td = $('<div class="matchDetailsArea"></div>');
        td.append(link);
        row.append(td);
    }

    // h2h button
    {
        var link = $('<a target="_blank" href="/goto.php?t=h&match_id=' + match_id + '" class="navH2h">H2H</a>');
        link.attr('title', match_name + ' Head to Head Stats');
        td = $('<div class="h2hArea"></div>');
        td.append(link);
        row.append(td);
    }

    // Odds button
    {
        var link = $('<a target="_blank" href="/goto.php?t=o&match_id=' + match_id + '" class="oddsDetails">Odds</a>');
        link.attr('title', match_name + ' Live Odds');
        td = $('<div class="oddsDetailsArea"></div>');
        td.append(link);
        row.append(td);
    }

    // stream button
    {
        if (match.streamed) {
            td = $('<div class="matchDetailsArea"></td>');
            var link = $('<a target="_blank" href="https://www.bet365.com/olp/open-account?affiliate=365_394716" class="smallDetails"><img src="/images/television.png"></a>');
            link.attr('title', 'Online Streaming ' + match_name + " ");
            td.append(link);
        } else {
            td = $('<div></div>');
            // var img = $('<img src="/images/television.png" title="Streaming not available">');
            // img.css('opacity', 0.4);
            // td.append(img);
        }
        row.append(td);
    }

    return row;

}
function buildMatchesTable(view_matches) {
    view_matches.sort(sort_mode == 1 ? sortByKickOff : sortByCompetitions);
    var crSeasonId = 0;
    var crSection = -1;
    var seFavCheck = null;
    var n = view_matches.length;
    var table = $('<table id="betList" class="competitionRanking"><thead><tr><th style="width:20px"></th><th style="width:70px"></th><th></th><th align="right">Home</th><th align="center">Score</th><th align="left">Away</th><th align="center">HT</th><th></th><th></th><th></th><th></th><th></th><th></th></tr></thead><tbody></tbody></table>');
    var allMatchRows = [];
    for (var i = 0; i < n; i++) {
        var match = view_matches[i];
        if (crSeasonId != match.season_id) {
            crSeasonId = match.season_id;
            crSection++;
            var area_name = sm_areas[match.area_id];
            var link = $('<a target="_blank" class="seasonLink" href="/goto.php?t=s&match_id=' + match.match_id + '"></a>');
            link.attr('title', area_name);
            link.text(area_name + ' - ' + match.leagueName);
            link.prepend('&nbsp;');
            link.prepend(getFlag(match.area_id));
            seFavCheck = $('<input type="checkbox" class="seFavCheck" checked="checked">');
            var td = $('<td colspan="13"></td>');
            td.append(seFavCheck);
            td.append('&nbsp;&nbsp;');
            td.append(link);
            td.append('<a class="topPageLink" href="#topPage">Top&#x25B2;</a>');
            var seasonRow = $('<tr class="seasonRow" data-section="' + crSection + '"></tr>');
            seasonRow.append(td);
            table.append(seasonRow);
        }
        if (!match.isFav) {
            seFavCheck.prop('checked', false);
        }
        var matchRow = generateMatchRow(match, crSection);
        allMatchRows.push(matchRow);
        table.append(matchRow);
        if (match.expanded) {
            var eventRows = generateMatchEventRows(match);
            var nEvents = eventRows.length;
            for (var ie = 0; ie < nEvents; ie++) {
                var eventRow = eventRows[ie];
                eventRow.show();
                table.append(eventRow);
            }
        }
    }
    zebraRows(allMatchRows);
    $("#livescore_matches").html(table);
}

var event_icons = {
    16: {"icon": "PG", "title": "Penalty"},
    17: {"icon": "PM", "title": "Penalty Miss"},
    23: {"icon": "PG", "title": "Penalty Shootout Goal"},
    22: {"icon": "PSM", "title": "Penalty Shootout Miss"},
    19: {"icon": "YC", "title": "Yellow Card"},
    21: {"icon": "Y2C", "title": "Second Yellow Card"},
    20: {"icon": "RC", "title": "Red Card"},
};
var goal_event_type_ids = ["14", "15", "16", "23"];
function generateMatchEventRows(match) {
    var eventRows = [];
    var events = match.events;
    var nEvents = events.length;
    var score = {};
    score[match.team_A_id] = 0;
    score[match.team_B_id] = 0;
    for (var i = 0; i < nEvents; i++) {
        var event = events[i];
        var id = event.id;
        var tdHome = $('<td colspan="4" class="evHome"></td>');
        var tdScore = $('<td class="evScore"></td>');
        var tdAway = $('<td colspan="8" class="evAway"></td>');
        var type_id = event.type_id;
        var icon = (type_id in event_icons) ? event_icons[type_id] : null;
        var team_id = event.participant_id;
        var isGoalType = goal_event_type_ids.includes(type_id);
        if (isGoalType) {
            // goal
            score[team_id]++;
            tdScore.text(score[match.team_A_id] + ' - ' + score[match.team_B_id]);
        } else {
            // card
            if (icon !== null) {
                tdScore.html('<img src="/images/icons/' + icon.icon + '.png" title="' + icon.title + '">');
            }
        }
        var timeText = '<span class="event_minute">' + event.minute + (event.extra_minute ? '+' + event.extra_minute : '') + '\'</span>';
        var player_name = $('<a target="_blank" href="' + (event.player_id ? '/player/' + event.player_id + '/' : '#') + '" class="playerLink playerText"></a>');
        player_name.text(event.player_name ? event.player_name : '');
        var codeTag = (isGoalType && icon !== null) ? '<img src="/images/icons/' + icon.icon + '.png" title="' + icon.title + '">' : '';
        var leftSide = (team_id === match.team_A_id);
        (leftSide ? tdAway : tdHome).html('&nbsp;'); // empty cell
        var fillCell = (leftSide ? tdHome : tdAway);
        if (leftSide) {
            fillCell.append(codeTag).append('&nbsp;').append(player_name).append('&nbsp;').append(timeText);
        } else {
            fillCell.append(timeText).append('&nbsp;').append(player_name).append('&nbsp;').append(codeTag);
        }
        var row = $('<tr class="matchEvents" data-event="' + id + '" data-match="' + event.match_id + '"></tr>');
        row.append(tdHome);
        row.append(tdScore);
        row.append(tdAway);
        eventRows.push(row);
    }
    return eventRows;
}

function generateMatchEventRowsCompact(match) {
    var eventRows = [];
    var events = match.events;
    var nEvents = events.length;
    var score = {};
    score[match.team_A_id] = 0;
    score[match.team_B_id] = 0;
    for (var i = 0; i < nEvents; i++) {
        var event = events[i];
        var id = event.id;
        var tdScore = $('<span class="evScore"></span>');
        var type_id = event.type_id;
        var icon = (type_id in event_icons) ? event_icons[type_id] : null;
        var team_id = event.participant_id;
        var isGoalType = goal_event_type_ids.includes(type_id);
        if (isGoalType) {
            // goal
            score[team_id]++;
            tdScore.text(score[match.team_A_id] + '-' + score[match.team_B_id]);
        } else {
            // card
            if (icon !== null) {
                tdScore.html('<img src="/images/icons/' + icon.icon + '.png" title="' + icon.title + '">');
            }
        }
        var timeText = '<span class="event_minute">' + event.minute + (event.extra_minute ? '+' + event.extra_minute : '') + '\'</span>';
        var player_name = $('<a target="_blank" href="' + (event.player_id ? '/player/' + event.player_id + '/' : '#') + '" class="playerLink playerText"></a>');
        player_name.text(event.player_name ? event.player_name : '');
        var leftSide = (team_id === match.team_A_id);
        var row = $('<div class="matchEvents lsmEvent" data-event="' + id + '" data-match="' + event.match_id + '"></div>');
        row.append(timeText);
        row.append(tdScore);
        var player_info = $('<span class="lsmPlayerInfo"></span>');
        player_info.append(player_name);
        var team_name = $('<span class="lsmPlayerTeam"></span>');
        team_name.text(leftSide ? match.ta_name : match.tb_name);
        player_info.append(team_name);
        row.append(player_info);
        eventRows.push(row);
    }
    return eventRows;
}
function generateMatchRowCompact(match, section, forScoreBar) {
    var match_id = match.match_id;
    var matchDiv = $('<div class="lsmMatchRow" data-match="' + match_id + '" data-section="' + section + '"></div>');
    if (forScoreBar) {
        matchDiv.append('<div class="lsmLatestGoal"><span class="lsmLatestGoalTxt">Goal!</span></div>');
    } else {
        matchDiv.append('<div class="lsmFavArea"><input type="checkbox" class="favCheck" ' + (match.isFav == '1' ? 'checked="checked"' : '') + '></div>');

        var lsmTime = $('<div class="lsmTime"><div class="lsmKickoff">' + timestamp_to_time(match.timestamp) + '</div></div>');
        var matchTime = $('<div class="lsmMatchTime"></div>');
        setMatchTime(matchTime, match);
        lsmTime.append(matchTime);
        matchDiv.append(lsmTime);
    }

    var matchTeams = $('<div class="lsmTeams"></div>');
    matchTeams.append(generateLsmTeamRow(match, 'a'));
    matchTeams.append(generateLsmTeamRow(match, 'b'));
    matchDiv.append(matchTeams);

    if (!forScoreBar) {
        var link = $('<a href="#" class="lsmMatchDetails" title="Toggle Events"></a>');
        link.text(match.expanded ? '-' : '+');
        var td = $('<div class="matchDetailsArea"></div>');
        td.append(link);
        matchDiv.append(td);
    }

    return matchDiv;
}

function generateLsmTeamRow(match, team) {
    var sideUC = team.toUpperCase();
    var sideLC = team.toLowerCase();
    var team_id = match['team_' + sideUC + '_id'];
    var name = match['t' + sideLC + '_name'];
    var area_id = match['t' + sideLC + '_area_id'];

    var teamRowDiv = $('<div class="lsmTeamRow"></div>');
    var td = $('<div class="lsmTeamName ' + (sideUC === 'A' ? 'teamHome' : 'teamAway') + '"></div>');

    var teamNameSpan = $('<span></span>');
    teamNameSpan.text(name);
    var flagImg = getFlag(area_id);
    var matchSideTag = (match.ng == 1) ? '<span title="Neutral Ground" class="matchSideTag">[N]</span>&nbsp;' : null;

    var card_count = {'yellowcard': 0, 'yellowred': 0, 'redcard': 0};
    $.each(match.events, function (i, event) {
        if (event.participant_id == team_id) {
            var type_id = event.type_id;
            if (type_id in type_id_to_name) {
                card_count[type_id_to_name[type_id]]++;
            }
        }
    });
    var cardsHtml = $.map(card_count, function (cnt, c) {
        if (cnt > 0) {
            return '<span class="' + c + '_count" title="' + cnt + ' ' + CARD_NAMES[c] + '">' + cnt + '</span>';
        }
    }).join('');

    var link = $('<a target="_blank" href="/goto.php?t=t' + sideLC + '&match_id=' + match.match_id + '" class="teamLink"></a>');
    link.append(flagImg);
    link.append('&nbsp;');
    link.append(teamNameSpan);
    td.append(link);
    if (cardsHtml != '') {
        td.append(cardsHtml);
    }
    teamRowDiv.append(td);
    teamRowDiv.append('<div class="lsmScore">' + match['score_' + sideUC] + '</div>');
    return teamRowDiv;
}

function generateMatchRow(match, section) {
    var td;
    var match_id = match.match_id;
    var row = $('<tr class="matchRow" data-match="' + match_id + '" data-section="' + section + '"></tr>');

    // favorite checkbox
    row.append('<td><input type="checkbox" class="favCheck" ' + (match.isFav == '1' ? 'checked="checked"' : '') + '></td>');

    // match start time
    row.append('<td><div class="score scoreF">' + timestamp_to_time(match.timestamp) + '</div></td>');

    // match period
    td = $('<td class="match_period_td"></td>');
    setMatchTime(td, match);
    row.append(td);

    // home team
    td = $('<td class="teamHome"></td>');
    setTeam(td, match, 'a');
    row.append(td);

    // score
    td = $('<td class="score"></td>');
    setScoreOrTime(td, match);
    row.append(td);

    // away team
    td = $('<td class="teamAway"></td>');
    setTeam(td, match, 'b');
    row.append(td);

    // HT
    if (match.hts_A !== null && match.hts_B !== null && (match.status === 'HT' || match.status === 'FT' || match.minute > 45)) {
        row.append('<td><div class="halfTimeScore" title="Half Time Score">' + match.hts_A + '-' + match.hts_B + '</div></td>');
    } else {
        row.append('<td><div class="halfTimeScore" title="Half Time Score">&nbsp;</div></td>');
    }

    var match_name = match.ta_name + ' vs ' + match.tb_name;

    // Bet button
    if (isFixtureStatusType(match.status) || isPlayingStatusType(match.status)) {
        var link = $('<a target="_blank" href="/goto.php?t=b&match_id=' + match_id + '" class="navBet">Play</a>');
        link.attr('title', 'Bet Now on ' + match_name + ' !');
        if (isPlayingStatusType(match.status)) {
            link.addClass('inplay_bet');
        }
        td = $('<td  class="nOutcomesArea" align="right"></td>');
        td.append(link);
        row.append(td);
    } else {
        row.append('<td></td>');
    }

    // Match button
    {
        var link = $('<a target="_blank" href="/goto.php?t=m&match_id=' + match_id + '" class="smallDetails"><img src="/images/matchstats-icon2.png"></a>');
        link.attr('title', 'Match Stats for ' + match_name);
        td = $('<td class="matchDetailsArea"></td>');
        td.append(link);
        row.append(td);
    }

    // h2h button
    {
        var link = $('<a target="_blank" href="/goto.php?t=h&match_id=' + match_id + '" class="navH2h">H2H</a>');
        link.attr('title', match_name + ' Head to Head Stats');
        td = $('<td  class="h2hArea"></td>');
        td.append(link);
        row.append(td);
    }

    // Odds button
    {
        var link = $('<a target="_blank" href="/goto.php?t=o&match_id=' + match_id + '" class="oddsDetails">Odds</a>');
        link.attr('title', match_name + ' Live Odds');
        td = $('<td  class="oddsDetailsArea"></td>');
        td.append(link);
        row.append(td);
    }

    // stream button
    {
        td = $('<td  class="matchDetailsArea"></td>');
        if (match.streamed) {
            var link = $('<a target="_blank" href="https://www.bet365.com/olp/open-account?affiliate=365_394716" class="smallDetails"><img src="/images/television.png"></a>');
            link.attr('title', 'Online Streaming ' + match_name + " ");
            td.append(link);
        } else {
            // var img = $('<img src="/images/television.png" title="Streaming not available">');
            // img.css('opacity', 0.4);
            // td.append(img);
        }
        row.append(td);
    }

    // match details
    {
        var link = $('<a href="#" class="lsMatchDetails" title="Toggle Events"></a>');
        link.text(match.expanded ? '-' : '+');
        td = $('<td  class="matchDetailsArea"></td>');
        td.append(link);
        row.append(td);
    }
    return row;
}

function old_setMatchTime(td, match) {
    if (isPlayedStatusType(match.status)) {
        td.html('<span class="match_period">' + match.status + '</span>');
    } else if (match.status === 'HT') {
        td.html('<span class="match_period">HT</span>');
    } else if (match.minute) {
        var minuteTxt = match.minute;
        if (match.second) {
            minuteTxt += '<span class="pblink">\'</span>';
            minuteTxt += (match.second < 10) ? "0" + match.second : match.second;
            minuteTxt += '<span class="pblink">"</span>';
        }
        if (match.extra_minute) {
            minuteTxt += '+' + match.extra_minute;
            minuteTxt += '<span class="pblink">\'</span>';
        }
        if (!match.second && !match.extra_minute) {
            minuteTxt += '<span class="pblink">\'</span>';
        }
        td.html('<span class="match_minute">' + minuteTxt + '</span>');
    } else {
        td.html('&nbsp;');
    }
}

function setMatchTime(td, match) {
    if (isPlayedStatusType(match.status)) {
        td.html('<span class="match_period">' + match.status + '</span>');
    } else if (match.status === 'HT') {
        td.html('<span class="match_period">HT</span>');
    } else if (match.minute) {
        var minuteTxt = format_match_time(match.minute)  /* + ':' + format_match_time(match.second) */;
        if (match.extra_minute) {
            minuteTxt += '+' + match.extra_minute;
        }
        td.html('<span class="ls_time">' + minuteTxt + '<span class="pblink">\'</span></span>');
    } else {
        td.html('&nbsp;');
    }
}

function format_match_time(val) {
    if (val === null) {
        return '00';
    }
    if (val < 10) {
        return '0' + val;
    }
    return val;
}

function zebraRows(rows) {
    var oddRow = true;
    var n = rows.length;
    for (var i = 0; i < n; i++) {
        var rowClass = oddRow ? 'odd' : 'even';
        var row = $(rows[i]);
        if (!row.hasClass(rowClass)) {
            row.removeClass(oddRow ? 'even' : 'odd');
            row.addClass(rowClass);
        }
        oddRow = !oddRow;
    }
}

function setScoreOrTime(td, match) {
    if (isFixtureStatusType(match.status)) {
        td.append('<div class="score scoreF">' + timestamp_to_time(match.timestamp) + '</div>');
    } else {
        // display score
        var div = $('<div class="score">' + match.score_A + ' - ' + match.score_B + '</div>');
        if (!score_plain) {
            var result = match.score_A == match.score_B ? 'D' : (match.score_A > match.score_B ? 'W' : 'L');
            div.addClass('score' + result);
        }
        td.append(div);
    }
}

/**
 * 
 * @param {$td} td
 * @param {match} match
 * @param {string} team 'A' or 'B'
 */
var type_id_to_name = {"19": 'yellowcard', "21": 'yellowred', "20": "redcard"};
function setTeam(td, match, team) {
    var sideUC = team.toUpperCase();
    var sideLC = team.toLowerCase();
    var team_id = match['team_' + sideUC + '_id'];
    var name = match['t' + sideLC + '_name'];
    var area_id = match['t' + sideLC + '_area_id'];

    var teamNameSpan = $('<span></span>');
    teamNameSpan.text(name);
    var flagImg = getFlag(area_id);
    var matchSideTag = (match.ng == 1) ? '<span title="Neutral Ground" class="matchSideTag">[N]</span>&nbsp;' : null;

    var card_count = {'yellowcard': 0, 'yellowred': 0, 'redcard': 0};
    $.each(match.events, function (i, event) {
        if (event.participant_id == team_id) {
            var type_id = event.type_id;
            if (type_id in type_id_to_name) {
                card_count[type_id_to_name[type_id]]++;
            }
        }
    });
    var cardsHtml = $.map(card_count, function (cnt, c) {
        if (cnt > 0) {
            return '<span class="' + c + '_count" title="' + cnt + ' ' + CARD_NAMES[c] + '">' + cnt + '</span>';
        }
    }).join('');

    var link = $('<a target="_blank" href="/goto.php?t=t' + sideLC + '&match_id=' + match.match_id + '" class="teamLink"></a>');
    if (sideUC == 'A') {
        if (cardsHtml != '') {
            td.append(cardsHtml);
        }
        if (matchSideTag) {
            link.append(matchSideTag);
        }
        link.append(teamNameSpan);
        link.append('&nbsp;');
        link.append(flagImg);
        td.append(link);
    } else {
        link.append(flagImg);
        link.append('&nbsp;');
        link.append(teamNameSpan);
        td.append(link);
        if (cardsHtml != '') {
            td.append(cardsHtml);
        }
    }

}

function getFlag(area_id) {
    var name = (area_id in sm_areas) ? sm_areas[area_id] : '';
    var flag = $('<img class="sm_flag" src="/images/sm/flags/' + area_id + '.svg" title="' + name + '" width="16" "height="16">');
    return flag;
}


function initFeed(data) {
    lastData = data;
    wireUIEvents();
    processFeed(data);
    requestFeed();
    setTimeout(onBlinkTimer, blinkPause);
}
function onFavChanges() {
    recalculateTabCount();
    if (crTab == TAB_FAVORITES) {
        rebuildView();
        rebuildScoreBar();
    }
}
function wireUIEvents() {
    $("#livescore_matches").delegate('.favCheck', 'change', function () {
        var check = $(this);
        var matchRow = check.parent().parent();
        var match_id = matchRow.data("match");
        var section = matchRow.data("section");
        var favorite = check.is(':checked') ? 1 : 0;
        var match = tracked_matches[match_id];
        match.isFav = favorite;
        match.favSince = Date.now();

        adjustSectionCheck($(".seasonRow[data-section=" + section + "]"));
        $.ajax({
            url: '/ls_fav_ajx.php',
            data: {
                match_ids: [match_id], favorite: favorite, favSince: match.favSince
            },
            cache: false
        });
        onFavChanges();
    });
    $("#livescore_matches").delegate('.seFavCheck', 'change', function () {
        var check = $(this);
        var section = check.parent().parent().data('section');
        var favorite = check.is(':checked') ? 1 : 0;
        var match_ids = [];
        var favSince = Date.now();
        $(".matchRow[data-section=" + section + "]").each(function (i, v) {
            var matchRow = $(v);
            var match_id = matchRow.data('match');
            var match = tracked_matches[match_id];
            match.isFav = favorite;
            match.favSince = favSince;
            match_ids.push(match_id);
            matchRow.find('.favCheck').prop('checked', favorite);
        });
        $.ajax({
            url: '/ls_fav_ajx.php',
            data: {
                match_ids: match_ids, favorite: favorite, favSince: favSince
            },
            cache: false
        });
        onFavChanges();
    });

    $(".feedArea").click(function (event) {
        event.preventDefault();
        var link = $(this);
        $(".feedArea").removeClass('crArea');
        link.addClass('crArea');
        area_id = link.data('id');
        viewNeedsRebuild = true;
        recalculateTabs = true;
        updateInterface();
    });
    $(".feedModeTab").click(function (event) {
        event.preventDefault();
        var tab = $(this);
        $(".feedModeTab").removeClass('activeMode');
        tab.addClass('activeMode');
        var newTab = tab.data('mode');
        if (crTab != newTab) {
            if (crTab == TAB_FAVORITES || newTab == TAB_FAVORITES) {
                scoreBarNeedsRebuild = true;
            }
            crTab = newTab;
            firstTabLoad = true;
            viewNeedsRebuild = true;
            updateInterface();
        }
    });
    $("#lssort").change(function () {
        sort_mode = $("#lssort").val();
        viewNeedsRebuild = true;
        updateInterface();
    });
    $("#lsscore").change(function () {
        score_plain = parseInt($("#lsscore").val());
        scoreBarNeedsRebuild = true;
        viewNeedsRebuild = true;
        updateInterface();
    });

    $("select.lsOption").change(function () {
        var s = $(this);
        var newValue = s.val();
        var opName = s.attr('name');
        $.ajax({
            url: '/ls_ajx.php',
            data: {
                type: 2, name: opName, value: newValue
            },
            dataType: 'json',
            cache: false
        });
    });

    $("select.soundOption").change(function () {
        var url = $(this).val();
        sound_play_file(url);
    });

    $("#lmExpander").click(function () {
        var control = $(this);
        var expanded = control.data('expanded');
        expanded = (expanded) ? 0 : 1;
        control.data('expanded', expanded);
        if (expanded) {
            if (renderSmallWindow) {
                $(".lmExtra").css('display', 'flex');
            } else {
                $(".lmExtra").show();
            }
            control.html('&#x25BC;');
        } else {
            $(".lmExtra").hide();
            control.html('&#x25c0;');
        }
    });

    $("#livescore_matches").delegate('.lsMatchDetails', 'click', function (event) {
        event.preventDefault();
        var link = $(this);
        var match_row = link.parent().parent();
        var match_id = match_row.data('match');
        var match = tracked_matches[match_id];
        if (match.expanded) {
            match.expanded = false;
            link.text('+');
            $('.matchEvents[data-match=' + match_id + ']').hide();
        } else {
            match.expanded = true;
            link.text('-');
            var existingRows = $('.matchEvents[data-match=' + match_id + ']');
            if (existingRows.length == match.events.length) {
                existingRows.show();
            } else {
                existingRows.remove();
                var evRows = generateMatchEventRows(match);
                var nEvents = evRows.length;
                for (var i = nEvents - 1; i >= 0; i--) {
                    var evRow = evRows[i];
                    evRow.show();
                    match_row.after(evRow);
                }
            }
        }
    });
    $("#livescore_matches").delegate('.lsmMatchDetails', 'click', function (event) {
        event.preventDefault();
        var link = $(this);
        var match_row = link.parent().parent();
        var match_id = match_row.data('match');
        var match = tracked_matches[match_id];
        var lsmExpanded = $('.lsmExpanded[data-match=' + match_id + ']');
        if (match.expanded) {
            match.expanded = false;
            link.text('+');
            lsmExpanded.hide();
        } else {
            match.expanded = true;
            link.text('-');
            var existingRows = $('.matchEvents[data-match=' + match_id + ']');
            if (lsmExpanded.length !== 0 && existingRows.length == match.events.length) {
                lsmExpanded.show();
            } else {
                lsmExpanded.remove();
                match_row.after(generateLsmExpanded(match));
            }
        }
    });
    $(".lsInfoMobile").delegate('.lsmMatchDetails', 'click', function (event) {
        event.preventDefault();
    });
}

function setBlink(mid, statName) {
    removeBlinkClassForMatchId(mid);
    blinkRows[mid] = {
        mid: mid,
        rowClass: "blink_" + statName,
        blinks: blinkCount

    };
}

function onBlinkTimer() {
    blinkOn = !blinkOn;
    if (blinkOn) {
        applyBlink();
    } else {
        removeBlink();
        for (var mid in blinkRows) {
            if (blinkRows.hasOwnProperty(mid)) {
                blinkRows[mid].blinks--;
                if (blinkRows[mid].blinks < 0) {
                    delete blinkRows[mid];
                }
            }
        }
    }
//    $(".inplay_bet").text(blinkOn ? "Bet" : "In-Play");
    setTimeout(onBlinkTimer, blinkPause);
}

function applyBlink() {
    for (var mid in blinkRows)
        if (blinkRows.hasOwnProperty(mid)) {
            var bd = blinkRows[mid];
            var row;
            if (renderSmallWindow) {
                row = $(".lsmMatchRow[data-match=" + mid + "]");
            } else {
                row = $(".matchRow[data-match=" + mid + "]");
            }
            if (row.length == 0)
                continue;
            row.addClass(bd.rowClass);
        }
}

function removeBlink() {
    for (var mid in blinkRows)
        if (blinkRows.hasOwnProperty(mid)) {
            removeBlinkClassForMatchId(mid);
        }
}

function removeBlinkClassForMatchId(mid) {
    if (mid in blinkRows) {
        var bd = blinkRows[mid];
        var row;
        if (renderSmallWindow) {
            row = $(".lsmMatchRow[data-match=" + mid + "]");
        } else {
            row = $(".matchRow[data-match=" + mid + "]");
        }
        if (row.length == 0)
            return;
        row.removeClass(bd.rowClass);
        var classStr = row.attr('class');
        if (classStr && classStr.indexOf("blink_") != -1) {
            // sometimes the class is not removed
            var classList = classStr.split(/\s+/);
            $.each(classList, function (index, item) {
                if (item.indexOf("blink_") == 0) {
                    row.removeClass(item);
                }
            });
        }
    }
}

function adjustSectionCheck(section) {
    var id = section.data('section');
    section.find('.seFavCheck').prop('checked', $('.matchRow[data-section="' + id + '"] .favCheck:not(:checked)').length == 0);
}

function restartFeed() {
    firstTabLoad = true;
    requestFeed();
}

function playAlert(evType) {
    var url = $("#ls" + evType).val();
    sound_play_file(url);
}

function requestFeed() {
    if (ajxTimer) {
        clearTimeout(ajxTimer);
    }
    reqCnt++;
    reqTs = Date.now();
    $.ajax({
        type: 'GET',
        url: '/ls_feed.php',
        data: {
            pc_id: lastData.change_id,
            favSince: lastData.favSince,
            req: reqCnt,
            reqm: matchesToRequest
        },
        dataType: 'json',
        cache: false,
        success: processFeed,
        error: onAjaxError,
        complete: onCompleteRequest
    });
    if (matchesToRequest.length > 0) {
        matchesToRequest = [];
    }
}

function processFeed(data) {
    reqRcv = Date.now();
    if (testDataHook != null) {
        data = testDataHook(data);
    }
    if (reqCnt && data.req != reqCnt)
        return; // feed out of order, skip
    lastData = data;

    calculateMatchTimestampRange();

    if (data.full) {
        tracked_matches = {};
        viewNeedsRebuild = true;
    }
    var n;

    var full = data.matches.full;
    n = full.length;
    for (var i = 0; i < n; i++) {
        addMatch(full[i]);
    }

    var stats = data.matches.stats;
    n = stats.length;
    for (var i = 0; i < n; i++) {
        addStats(stats[i]);
    }

    var minute = data.matches.minute;
    n = minute.length;
    for (var i = 0; i < n; i++) {
        addMinute(minute[i]);
    }

    n = data.events.length;
    for (var i = 0; i < n; i++) {
        addMatchEvent(data.events[i]);
    }

    n = data.fav.length;
    for (var i = 0; i < n; i++) {
        updateFav(data.fav[i]);
    }

    updateInterface();
    playSoundAlerts();
    traceStats(data);
}

function updateFav(fav) {
    var match_id = fav.match_id;
    if (!(match_id in tracked_matches)) {
        return;
    }
    var match = tracked_matches[match_id];
    if (fav.favSince > match.favSince) {
        match.isFav = fav.isFav;
        match.favSince = fav.favSince;
        if (match.displayed) {
            var matchRow = $('.matchRow[data-match=' + match_id + ']');
            if (matchRow.length > 0) {
                var input = matchRow.find('.favCheck');
                var isFav = (match.isFav == 1);
                if (input.is(':checked') != isFav) {
                    input.prop('checked', isFav);
                    var section = matchRow.data('section');
                    adjustSectionCheck($("#sec" + section));
                }
            }
        }
        if (crTab == TAB_FAVORITES) {
            viewNeedsRebuild = true;
            scoreBarNeedsRebuild = true;
        }
        recalculateTabs = true;
    }
}

function updateInterface() {
    if (viewNeedsRebuild) {
        rebuildView();
    }
    if (scoreBarNeedsRebuild) {
        rebuildScoreBar();
    }
    if (recalculateTabs) {
        recalculateTabCount();
    }
}

function rebuildScoreBar() {
    var matches = [];
    $.each(tracked_matches, function (i, match) {
        if (match.last_score_ts > 0 && (crTab != TAB_FAVORITES || match.isFav)) {
            matches.push(match);
        }
    });
    matches.sort(function (a, b) {
        return b.last_score_ts - a.last_score_ts;
    });
    var maxLastMatches = renderSmallWindow ? 3 : 10;
    var n = Math.min(matches.length, maxLastMatches);
    renderSmallWindow = isSmallWindow();
    var table;
    if (renderSmallWindow) {
        table = $('<div id="lastMatchesWithGoals"></div>');
    } else {
        table = $('<table class="competitionRanking" id="lastMatchesWithGoals"></table>');
    }
    var hideExtra = !($("#lmExpander").data('expanded'));
    var allRows = [];
    for (var i = 0; i < n; i++) {

        var tr;
        if (renderSmallWindow) {
            tr = generateMatchRowCompact(matches[i], -1, true);
        } else {
            tr = buildScoreBarRow(matches[i]);
        }
        if (i > 0) {
            tr.addClass("lmExtra");
            if (hideExtra) {
                tr.addClass("off");
            }
        }
        table.append(tr);
        allRows.push(tr);
    }
    $("#lmHolder").html(table);
    /*zebraRows(allRows); */
    scoreBarNeedsRebuild = false;
}

function buildScoreBarRow(match) {
    var match_id = match.match_id;
    var tr = $('<tr data-match="' + match_id + '"></tr>');
    tr.append('<td class="lmLeftSpacer"></td>');
    tr.append('<td class="score lmGoalTime"><div class="score scoreF">' + timestamp_to_time(match.last_score_ts) + '</div></td>');
    tr.append('<td class="match_period_td_spacer">&nbsp;</td>');
    var td;
    // home team
    td = $('<td class="teamHome"></td>');
    setTeam(td, match, 'a');
    tr.append(td);

    // score
    td = $('<td class="score"></td>');
    setScoreOrTime(td, match);
    tr.append(td);

    // away team
    td = $('<td class="teamAway"></td>');
    setTeam(td, match, 'b');
    tr.append(td);

    // competition
    td = $('<td class="lmComp"></td>');
    var area_name = sm_areas[match.area_id];
    var link = $('<a target="_blank" class="seasonLink" href="/goto.php?t=s&match_id=' + match_id + '"></a>');
    link.attr('title', area_name);
    link.text(match.leagueName);
    link.prepend('&nbsp;');
    link.prepend(getFlag(match.area_id));
    td.append(link);
    tr.append(td);

    return tr;
}

function recalculateTabCount() {
    var tabCount = [0, 0, 0, 0, 0];
    var nTabs = tabCount.length;
    for (var match_id in tracked_matches) {
        if (tracked_matches.hasOwnProperty(match_id)) {
            var match = tracked_matches[match_id];
            if (match.timestamp >= matchTimestampMin && match.timestamp <= matchTimestampMax && (area_id == 0 || area_id == match.area_id)) {
                for (var i = 0; i < nTabs; i++) {
                    if (tabFilters[i](match)) {
                        tabCount[i]++;
                    }
                }
            }
        }
    }

    for (var i = 0; i < nTabs; i++) {
        $("#betDateNav li[data-mode=" + i + "] .lsMatchCount").text(tabCount[i]);
    }
    recalculateTabs = false;
}

function traceStats(data) {
    var trace_div = $("#livescore_trace");
    if (trace_div.length > 0) {
        var finalFeedTs = Date.now();
        var feedGeneration = Math.round(data.gentime * 1000);
        var feedDownload = reqRcv - reqTs;
        var feedNetwork = (feedDownload > feedGeneration) ? (feedDownload - feedGeneration) : feedDownload;
        var jsUpdate = finalFeedTs - reqRcv;
        var frameTime = finalFeedTs - reqTs;
        trace_div.html("<b>Status</b><br>"
                + "request#: " + reqCnt + "<br>"
                + "server load: " + data.load + "<br>"
                + "feed generation: " + feedGeneration + " ms<br>"
                + "feed network time: " + feedNetwork + " ms<br>"
                + "feed download total: " + feedDownload + " ms<br>"
                + "javascript update: " + jsUpdate + " ms<br>"
                + "frame time: " + frameTime + " ms<br><br>"
                );
    }
}

function playSoundAlerts() {
    for (var soundAlert in soundAlerts)
        if (soundAlerts.hasOwnProperty(soundAlert) && soundAlerts[soundAlert]) {
            soundAlerts[soundAlert] = false;
            playAlert(soundAlert);
        }
}

function setBlink(mid, statName) {
    blinkRows[mid] = {
        mid: mid,
        rowClass: "blink_" + statName,
        blinks: blinkCount

    };
}

function onAjaxError() {
    // ignore
}

function onCompleteRequest() {
    if (dbg_stop) {
        return;
    }
    ajxTimer = setTimeout('requestFeed()', refreshTime * 1000);
}

function takeAlertSnapshot(match) {
    var snap = {
        score_A: match.score_A,
        score_B: match.score_B,
        match_period: match.status,
        red_A: 0,
        red_B: 0,
        yellow_A: 0,
        yellow_B: 0
    };
    // count cards
    var team_A_id = match.team_A_id;
    var events = match.events;
    var n = events.length;
    for (var i = 0; i < n; i++) {
        var event = events[i];
        var type_id = event.type_id;
        if (type_id == 20 || type_id == 21) {
            if (event.participant_id == team_A_id) {
                snap.red_A++;
            } else {
                snap.red_B++;
            }
        }
        if (type_id == 19) {
            if (event.participant_id == team_A_id) {
                snap.yellow_A++;
            } else {
                snap.yellow_B++;
            }
        }
    }
    return snap;
}

function checkForAlerts(match, prevSnap) {
    var snap = takeAlertSnapshot(match);
    var match_id = match.match_id;
    if ((snap.match_period == 'HT' || snap.match_period == 'FT') &&
            (prevSnap.match_period != 'HT' && prevSnap.match_period != 'FT')) {
        alertHtFt(match_id);
    }
    if (snap.score_A > prevSnap.score_A) {
        alertGoal(match_id, true);
    }
    if (snap.score_B > prevSnap.score_B) {
        alertGoal(match_id, false);
    }
    if (snap.score_A < prevSnap.score_A) {
        alertCanceledGoal(match_id, true);
    }
    if (snap.score_B < prevSnap.score_B) {
        alertCanceledGoal(match_id, false);
    }
    if (snap.red_A > prevSnap.red_A) {
        alertRedCard(match_id, true);
    }
    if (snap.red_B > prevSnap.red_B) {
        alertRedCard(match_id, false);
    }
    if (snap.yellow_A > prevSnap.yellow_A) {
        alertYellowCard(match_id, true);
    }
    if (snap.yellow_B > prevSnap.yellow_B) {
        alertYellowCard(match_id, false);
    }
}

function alertHtFt(match_id) {
    soundAlerts.pauseend = true;
    setBlink(match_id, 'match_period');
}
function alertGoal(match_id, sideA) {
    soundAlerts.goals = true;
    setBlink(match_id, sideA ? 'score_A' : 'score_B');
}
function alertCanceledGoal(match_id, sideA) {
    soundAlerts.canceled = true;
    setBlink(match_id, sideA ? 'cancel_A' : 'cancel_B');
}
function alertRedCard(match_id, sideA) {
    soundAlerts.redcards = true;
    setBlink(match_id, sideA ? 'red_A' : 'red_B');
}

function alertYellowCard(match_id, sideA) {
    soundAlerts.yellowcards = true;
    setBlink(match_id, sideA ? 'yellow_A' : 'yellow_B');
}

function addStreamedMatches(match_list) {
    var n = match_list.length;
    for (var i = 0; i < n; i++) {
        streamed_matches[match_list[i]] = true;
    }
}
