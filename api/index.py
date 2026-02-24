"""
한영자 희망 장학재단 장학생 선발 시스템 — Vercel Flask REST API
후원사: 삼양 | 수여식: 2026년 4월 30일
이사장: 전동진 | 사무국장: 임재영
"""

import io
import json
import os
import re
import math
import zipfile
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader
from flask import Flask, jsonify, request

# ──────────────────────────────────────────────────────────────────────
# 프론트엔드 HTML — 파일 시스템 의존 없이 직접 내장
# (Vercel 서버리스 환경에서 includeFiles가 불안정하므로 임베드 방식 사용)
# ──────────────────────────────────────────────────────────────────────
_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>한영자 희망 장학재단 | 장학생 선발 시스템</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <style>
    :root { --navy:#0d1b5e; --navy2:#1a3a8f; }
    body { background:#f5f7fb; font-family:'Segoe UI',sans-serif; }
    .site-header {
      background:linear-gradient(135deg,var(--navy),var(--navy2));
      color:#fff; padding:2rem 1.5rem; text-align:center;
      border-radius:0 0 16px 16px; margin-bottom:1.5rem;
      box-shadow:0 4px 20px rgba(13,27,94,.3);
    }
    .site-header h1 { font-size:2rem; font-weight:900; letter-spacing:2px; margin:0; }
    .site-header p  { margin:.3rem 0 0; opacity:.8; font-size:.9rem; }
    .nav-tabs .nav-link        { color:#555; font-weight:600; }
    .nav-tabs .nav-link.active { color:var(--navy); border-bottom:3px solid var(--navy); }
    .card { border:none; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,.08); }
    .card-header { background:var(--navy); color:#fff; border-radius:12px 12px 0 0 !important; font-weight:700; }
    .metric-card { border-left:5px solid var(--navy); }
    .upload-zone {
      border:2px dashed #aab4cc; border-radius:12px;
      padding:2.5rem; text-align:center; cursor:pointer; transition:background .2s;
    }
    .upload-zone:hover,.upload-zone.dragover { background:#e8ecf8; border-color:var(--navy2); }
    .upload-zone i { font-size:3rem; color:#aab4cc; }
    .table-scroll { overflow-x:auto; max-height:540px; overflow-y:auto; }
    .table thead { position:sticky; top:0; z-index:10; }
    .table thead th { background:var(--navy); color:#fff; white-space:nowrap; }
    .rank-1 { background:rgba(255,215,0,.25) !important; font-weight:700; }
    .rank-2 { background:rgba(192,192,192,.25) !important; font-weight:700; }
    .rank-3 { background:rgba(205,127,50,.25) !important; font-weight:700; }
    .check-mark { color:#198754; font-weight:700; }
    .report-box { background:#eef2ff; border-left:5px solid var(--navy); padding:1.4rem 1.8rem; border-radius:8px; line-height:1.9; }
    #loadingSection { display:none; }
    footer { text-align:center; color:#888; font-size:.82rem; padding:1.5rem 0 2rem; }
    .log-box { background:#1e1e2e; color:#a9b1d6; font-family:monospace; font-size:.78rem; padding:1rem; border-radius:8px; max-height:240px; overflow-y:auto; white-space:pre; }
  </style>
</head>
<body>
<div class="site-header">
  <h1>🎓 한영자 희망 장학재단</h1>
  <p>장학생 자동 선발 시스템 &nbsp;|&nbsp; 후원사: 삼양</p>
  <p style="font-size:.8rem;opacity:.65;">수여식: 2026년 4월 30일 &nbsp;·&nbsp; 이사장: 전동진 &nbsp;·&nbsp; 사무국장: 임재영</p>
</div>

<div class="container-fluid px-4" style="max-width:1280px;">
  <div id="alertBox"></div>

  <ul class="nav nav-tabs mb-3" id="mainTab">
    <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#tabUpload"><i class="bi bi-upload"></i> 서류 업로드</a></li>
    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#tabResult"><i class="bi bi-trophy"></i> 선발 결과</a></li>
    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#tabStats"><i class="bi bi-bar-chart-line"></i> 통계 리포트</a></li>
  </ul>

  <div class="tab-content">

    <!-- 탭1: 업로드 -->
    <div class="tab-pane fade show active" id="tabUpload">
      <div class="row g-3">
        <div class="col-lg-7">
          <div class="card">
            <div class="card-header"><i class="bi bi-folder-plus"></i> 서류 ZIP 업로드</div>
            <div class="card-body">
              <p class="text-muted small mb-3">신청자별 폴더에 <strong>4종 서류</strong>(자립지원 대상자 확인서, 재학증명서, 성적증명서, 가산점 서류)가 담긴 ZIP 파일을 업로드하세요.</p>
              <div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()">
                <i class="bi bi-file-earmark-zip"></i>
                <p class="mt-2 mb-0 fw-semibold">여기를 클릭하거나 ZIP 파일을 드래그 앤 드롭</p>
                <p class="text-muted small">최대 50MB</p>
              </div>
              <input type="file" id="fileInput" accept=".zip" class="d-none" onchange="onFileSelect(this)" />
              <div id="fileInfo" class="mt-2 small text-success d-none"></div>
              <div class="d-flex gap-2 mt-3">
                <button class="btn btn-primary flex-grow-1" id="uploadBtn" onclick="uploadFile()" disabled><i class="bi bi-search"></i> 분석 시작</button>
                <button class="btn btn-outline-secondary flex-grow-1" onclick="runDemo()"><i class="bi bi-flask"></i> 데모 테스트</button>
              </div>
            </div>
          </div>
        </div>
        <div class="col-lg-5">
          <div class="card h-100">
            <div class="card-header"><i class="bi bi-info-circle"></i> 선발 기준 안내</div>
            <div class="card-body small">
              <table class="table table-sm table-bordered mb-2">
                <thead class="table-light"><tr><th>항목</th><th>배점</th></tr></thead>
                <tbody>
                  <tr><td>학년 점수</td><td>최대 50점</td></tr>
                  <tr><td>학업 이수율</td><td>최대 50점</td></tr>
                  <tr><td>가산점</td><td>최대 10점</td></tr>
                </tbody>
              </table>
              <p class="fw-semibold mb-1">학년별 점수</p>
              <ul class="mb-2">
                <li>4학년 → 50점 &nbsp;|&nbsp; 3학년 → 35점</li>
                <li>2학년 → 20점 &nbsp;|&nbsp; 1학년 → 5점</li>
              </ul>
              <p class="fw-semibold mb-1">가산점 세부</p>
              <ul class="mb-2">
                <li>이공계/방산 전공 → <span class="text-success fw-bold">+5</span></li>
                <li>국가자격증/어학 → <span class="text-success fw-bold">+3</span></li>
                <li>봉사 50h 이상 → <span class="text-success fw-bold">+2</span></li>
              </ul>
              <div class="alert alert-warning py-2 mb-0 small"><i class="bi bi-shield-lock"></i> 주민번호 등 민감 정보는 추출 즉시 마스킹됩니다.</div>
            </div>
          </div>
        </div>
        <div class="col-12">
          <div class="d-flex align-items-center gap-2 p-2 border rounded bg-white">
            <div class="flex-grow-1" id="excludeStatus"></div>
            <button class="btn btn-outline-danger btn-sm d-none" id="excludeClearBtn" onclick="clearExcluded()"><i class="bi bi-x-circle"></i> 초기화</button>
          </div>
        </div>
        <div class="col-12">
          <div class="card">
            <div class="card-header"><i class="bi bi-folder-symlink"></i> ZIP 파일 구조 예시</div>
            <div class="card-body">
              <pre class="mb-0 small bg-light p-3 rounded">📦 신청서류.zip
├── 홍길동/
│   ├── 자립지원대상자확인서.pdf
│   ├── 재학증명서.pdf
│   ├── 성적증명서.pdf
│   └── 가산점서류.pdf
└── 김철수/ ...</pre>
              <p class="mt-2 mb-0 text-muted small">※ <strong>자립지원 대상자 확인서</strong>가 없는 신청자는 자동으로 선발 대상에서 제외됩니다.</p>
            </div>
          </div>
        </div>
      </div>

      <div id="loadingSection" class="text-center py-5">
        <div class="spinner-border text-primary" style="width:3rem;height:3rem;"></div>
        <p class="mt-3 fw-semibold text-secondary" id="loadingText">서류를 분석하고 있습니다...</p>
      </div>

      <div class="mt-3 d-none" id="logSection">
        <div class="accordion">
          <div class="accordion-item">
            <h2 class="accordion-header">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#logCollapse">
                <i class="bi bi-journal-text me-2"></i> 처리 로그 (투명성 원칙에 따른 처리 이력)
              </button>
            </h2>
            <div id="logCollapse" class="accordion-collapse collapse">
              <div class="accordion-body p-0"><div class="log-box" id="logContent"></div></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 탭2: 선발 결과 -->
    <div class="tab-pane fade" id="tabResult">
      <div id="resultEmpty" class="text-center text-muted py-5">
        <i class="bi bi-arrow-left-circle" style="font-size:2rem;"></i>
        <p class="mt-2">'서류 업로드' 탭에서 분석을 먼저 실행하세요.</p>
      </div>
      <div id="resultContent" class="d-none">
        <div class="alert alert-success d-flex align-items-start mb-3">
          <i class="bi bi-trophy-fill me-2 mt-1" style="font-size:1.3rem;"></i>
          <div>
            <strong>2026년도 한영자 희망 장학재단 장학생 최종 선발 명단</strong>
            <div class="small text-muted mt-1" id="resultMeta"></div>
          </div>
        </div>
        <div class="row g-2 mb-3" id="resultMetrics"></div>
        <div class="d-flex gap-2 mb-3 flex-wrap">
          <button class="btn btn-success btn-sm" onclick="downloadCSV('selected')"><i class="bi bi-download"></i> 선발 명단 CSV</button>
          <button class="btn btn-outline-secondary btn-sm" onclick="downloadCSV('all')"><i class="bi bi-download"></i> 전체 자격자 CSV</button>
        </div>
        <div class="card mb-3">
          <div class="card-header"><i class="bi bi-table"></i> 최종 선발 명단</div>
          <div class="card-body p-0">
            <div class="table-scroll">
              <table class="table table-hover table-sm mb-0">
                <thead><tr><th>순위</th><th>성명</th><th>학년</th><th>전공</th><th>이수학점</th><th>졸업기준</th><th>이수율(%)</th><th>GPA</th><th>학년점수</th><th>이수율점수</th><th>가산점</th><th>총점</th><th>이공계</th><th>자격증</th><th>봉사</th></tr></thead>
                <tbody id="resultTbody"></tbody>
              </table>
            </div>
          </div>
        </div>
        <div id="warningSection" class="d-none">
          <div class="accordion">
            <div class="accordion-item border-warning">
              <h2 class="accordion-header">
                <button class="accordion-button collapsed bg-warning bg-opacity-10" type="button" data-bs-toggle="collapse" data-bs-target="#warnCollapse">
                  <i class="bi bi-exclamation-triangle me-2 text-warning"></i><span id="warnCount"></span>
                </button>
              </h2>
              <div id="warnCollapse" class="accordion-collapse collapse">
                <div class="accordion-body p-0">
                  <table class="table table-sm mb-0"><thead><tr><th>성명</th><th>주의사항</th></tr></thead><tbody id="warnTbody"></tbody></table>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 탭3: 통계 -->
    <div class="tab-pane fade" id="tabStats">
      <div id="statsEmpty" class="text-center text-muted py-5">
        <i class="bi bi-arrow-left-circle" style="font-size:2rem;"></i>
        <p class="mt-2">'서류 업로드' 탭에서 분석을 먼저 실행하세요.</p>
      </div>
      <div id="statsContent" class="d-none">
        <div class="row g-2 mb-3" id="statsMetrics"></div>
        <div class="row g-3 mb-3">
          <div class="col-md-6"><div class="card"><div class="card-header"><i class="bi bi-bar-chart"></i> 학년별 선발 인원</div><div class="card-body"><canvas id="gradeChart" height="220"></canvas></div></div></div>
          <div class="col-md-6"><div class="card"><div class="card-header"><i class="bi bi-graph-up"></i> 선발자 점수 분포</div><div class="card-body"><canvas id="scoreChart" height="220"></canvas></div></div></div>
        </div>
        <div class="row g-2 mb-3" id="bonusMetrics"></div>
        <div class="card">
          <div class="card-header"><i class="bi bi-file-earmark-text"></i> 선발 취지 보고서</div>
          <div class="card-body"><div class="report-box" id="reportBox"></div></div>
        </div>
      </div>
    </div>

  </div>
</div>

<footer>
  한영자 희망 장학재단 장학생 선발 시스템 &nbsp;|&nbsp; 이사장 전동진 印 &nbsp;·&nbsp; 사무국장 임재영 印<br>
  본 시스템은 「개인정보보호법」에 따라 주민등록번호 등 민감 정보를 마스킹 처리합니다.
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
let G = { selected:[], all:[], stats:null, warnings:[], log:'' };
let gradeChart=null, scoreChart=null;

function onFileSelect(input) {
  const f = input.files[0]; if(!f) return;
  const el = document.getElementById('fileInfo');
  el.textContent = '✅ ' + f.name + '  (' + (f.size/1024).toFixed(1) + ' KB)';
  el.classList.remove('d-none');
  document.getElementById('uploadBtn').disabled = false;
}

const zone = document.getElementById('uploadZone');
zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('dragover'); });
zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
zone.addEventListener('drop', e => {
  e.preventDefault(); zone.classList.remove('dragover');
  const dt = new DataTransfer(); dt.items.add(e.dataTransfer.files[0]);
  const fi = document.getElementById('fileInput'); fi.files = dt.files; onFileSelect(fi);
});

async function uploadFile() {
  const f = document.getElementById('fileInput').files[0]; if(!f) return;
  const fd = new FormData(); fd.append('file', f);
  await callAPI('/api/upload', fd);
}
async function runDemo() { await callAPI('/api/demo', new FormData(), '데모 데이터로 분석 중...'); }

async function callAPI(url, body, msg='서류를 분석하고 있습니다...') {
  if(url==='/api/upload') { body.append('excluded_names', JSON.stringify([...loadExcluded()])); }
  setLoading(true, msg); clearAlert();
  try {
    const res  = await fetch(url, {method:'POST', body});
    const data = await res.json();
    if(!data.success) throw new Error(data.error || '알 수 없는 오류');
    applyData(data);
    showAlert('success', '🎉 분석 완료! 총 <strong>' + data.total_applicants + '명</strong> 중 <strong>' + data.selected_count + '명</strong> 최종 선발' + (data.is_demo?' <span class="badge bg-warning text-dark">데모</span>':''));
    new bootstrap.Tab(document.querySelector('[href="#tabResult"]')).show();
  } catch(e) { showAlert('danger','❌ '+e.message); }
  finally { setLoading(false); }
}

function applyData(data) {
  G.selected=data.results||[]; G.all=data.all_results||[];
  G.stats=data.stats||{}; G.warnings=data.warnings||[]; G.log=data.log||'';
  if(!data.is_demo && G.selected.length>0) addToExcluded(G.selected.map(r=>r['성명']));
  renderResult(data); renderStats(data.stats);
  if(G.log){ document.getElementById('logContent').textContent=G.log; document.getElementById('logSection').classList.remove('d-none'); }
}

function renderResult(data) {
  document.getElementById('resultEmpty').classList.add('d-none');
  document.getElementById('resultContent').classList.remove('d-none');
  const now = new Date();
  document.getElementById('resultMeta').innerHTML = '선발 기준일: '+now.toLocaleDateString('ko-KR')+' &nbsp;|&nbsp; 수여식: 2026년 4월 30일 &nbsp;|&nbsp; 이사장 전동진 印 &nbsp;|&nbsp; 사무국장 임재영 印';
  document.getElementById('resultMetrics').innerHTML = mkMetrics([
    {label:'총 신청자', value:data.total_applicants+'명', icon:'people'},
    {label:'자격 충족', value:data.eligible_count+'명',   icon:'person-check'},
    {label:'최종 선발', value:data.selected_count+'명',   icon:'trophy', color:'text-success'},
  ]);
  const tb = document.getElementById('resultTbody'); tb.innerHTML='';
  G.selected.forEach(r => {
    const cls = r['순위']===1?'rank-1':r['순위']===2?'rank-2':r['순위']===3?'rank-3':'';
    tb.insertAdjacentHTML('beforeend','<tr class="'+cls+'"><td><strong>'+r['순위']+'</strong></td><td>'+esc(r['성명'])+'</td><td>'+esc(r['학년'])+'</td><td class="text-nowrap">'+esc(r['전공'])+'</td><td>'+r['이수학점']+'</td><td>'+r['졸업기준학점']+'</td><td><strong>'+r['이수율']+'%</strong></td><td>'+r['GPA']+'</td><td>'+r['학년점수']+'</td><td>'+r['이수율점수']+'</td><td>'+r['가산점']+'</td><td><strong>'+r['총점']+'</strong></td><td class="check-mark text-center">'+(r['이공계방산']||'')+'</td><td class="check-mark text-center">'+(r['자격증어학']||'')+'</td><td class="check-mark text-center">'+(r['봉사50h']||'')+'</td></tr>');
  });
  if(G.warnings.length>0){
    document.getElementById('warningSection').classList.remove('d-none');
    document.getElementById('warnCount').textContent='파싱 주의사항 ('+G.warnings.length+'건)';
    const wb=document.getElementById('warnTbody'); wb.innerHTML='';
    G.warnings.forEach(w=>wb.insertAdjacentHTML('beforeend','<tr><td>'+esc(w.name)+'</td><td class="small">'+esc(w.note)+'</td></tr>'));
  }
}

function renderStats(stats) {
  if(!stats) return;
  document.getElementById('statsEmpty').classList.add('d-none');
  document.getElementById('statsContent').classList.remove('d-none');
  document.getElementById('statsMetrics').innerHTML = mkMetrics([
    {label:'총 신청자',   value:stats.total_applicants+'명', icon:'people'},
    {label:'최종 선발',   value:stats.selected_count+'명',   icon:'trophy', color:'text-success'},
    {label:'선발률',      value:stats.selection_rate+'%',    icon:'percent'},
    {label:'평균 점수',   value:stats.avg_score+'점',        icon:'star'},
    {label:'평균 이수율', value:stats.avg_completion+'%',    icon:'journal-check'},
  ]);
  document.getElementById('bonusMetrics').innerHTML = mkMetrics([
    {label:'이공계/방산 전공자', value:stats.stem_count+'명 ('+stats.stem_rate+'%)', icon:'cpu'},
    {label:'자격증/어학 성적',   value:stats.cert_count+'명', icon:'award'},
    {label:'봉사 50h 이상',      value:stats.vol_count+'명',  icon:'heart'},
  ]);
  const gl=Object.keys(stats.grade_dist).sort().reverse();
  mkChart('gradeChart', gl, gl.map(k=>stats.grade_dist[k]), '선발 인원','#1a3a8f', c=>gradeChart=c, gradeChart);
  const sl=G.selected.map((_,i)=>(i+1)+'위'), sd=G.selected.map(r=>r['총점']);
  mkChart('scoreChart', sl, sd, '총점','#2e7d32', c=>scoreChart=c, scoreChart);
  document.getElementById('reportBox').innerHTML =
    '<strong>한영자 희망 장학재단 2026년도 장학생 선발 결과 보고</strong><br><br>' +
    '본 재단은 <strong>자립준비청년의 실질적 자립 지원</strong>을 목적으로, 자립지원 대상자 <strong>'+stats.total_applicants+'명</strong>의 지원서를 심사하였습니다.<br><br>' +
    '학년 점수, 학업 이수율, 사회적 역량을 종합하여 <strong>'+stats.selected_count+'명</strong>을 최종 선발하였으며, 평균 점수는 <strong>'+stats.avg_score+'점</strong> (최고 '+stats.max_score+'점 / 최저 '+stats.min_score+'점), 평균 이수율은 <strong>'+stats.avg_completion+'%</strong>입니다.<br><br>' +
    '후원사 <strong>삼양</strong>의 방산기업 특성을 반영하여 이공계·방산 전공자 <strong>'+stats.stem_count+'명('+stats.stem_rate+'%)</strong>에게 가산점이 부여되었습니다. 수여식은 <strong>2026년 4월 30일</strong>입니다.<br><br>' +
    '<em>이사장 전동진 &nbsp;印 &nbsp;&nbsp; 사무국장 임재영 &nbsp;印</em>';
}

function mkChart(id, labels, data, label, color, setter, old) {
  if(old) old.destroy();
  setter(new Chart(document.getElementById(id).getContext('2d'),{type:'bar',data:{labels,datasets:[{label,data,backgroundColor:color+'cc',borderColor:color,borderWidth:1}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{stepSize:1}}}}}));
}

function downloadCSV(type) {
  const rows = type==='selected'?G.selected:G.all;
  if(!rows||!rows.length) return;
  const excl=new Set(['_학년숫자','_이수율정렬']);
  const hdr=Object.keys(rows[0]).filter(k=>!excl.has(k));
  const lines=[hdr.join(','),...rows.map(r=>hdr.map(h=>{const v=r[h]??''; return /[,"\n]/.test(String(v))?'"'+String(v).replace(/"/g,'""')+'"':v;}).join(','))];
  const blob=new Blob(['\uFEFF'+lines.join('\n')],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=url; a.download=(type==='selected'?'한영자 희망 장학재단_선발명단_':'한영자 희망 장학재단_전체명단_')+new Date().toISOString().slice(0,10).replace(/-/g,'')+'.csv';
  a.click(); URL.revokeObjectURL(url);
}

function mkMetrics(items){return items.map(m=>'<div class="col-sm-6 col-lg-auto flex-grow-1"><div class="card metric-card p-3 h-100"><div class="text-muted small"><i class="bi bi-'+m.icon+' me-1"></i>'+m.label+'</div><div class="fs-3 fw-bold mt-1 '+(m.color||'text-dark')+'">'+m.value+'</div></div></div>').join('');}
function setLoading(on,msg=''){document.getElementById('loadingSection').style.display=on?'block':'none';document.getElementById('loadingText').textContent=msg;document.getElementById('uploadBtn').disabled=on;}
function showAlert(type,html){document.getElementById('alertBox').innerHTML='<div class="alert alert-'+type+' alert-dismissible fade show" role="alert">'+html+'<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>';}
function clearAlert(){document.getElementById('alertBox').innerHTML='';}
function esc(s){return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// ── 이전 선발자 제외 관리 (localStorage 영속화) ──
const _EK='hanyang_excluded';
function loadExcluded(){try{return new Set(JSON.parse(localStorage.getItem(_EK)||'[]'));}catch{return new Set();}}
function saveExcluded(s){localStorage.setItem(_EK,JSON.stringify([...s]));}
function addToExcluded(names){const s=loadExcluded();names.forEach(n=>s.add(n));saveExcluded(s);updateExcludeUI();}
function clearExcluded(){if(!confirm('이전 선발 명단을 초기화하시겠습니까?\n초기화 시 중복 선발 방지가 리셋됩니다.'))return;localStorage.removeItem(_EK);updateExcludeUI();}
function updateExcludeUI(){
  const s=loadExcluded(),el=document.getElementById('excludeStatus'),btn=document.getElementById('excludeClearBtn');
  if(!el)return;
  if(s.size===0){
    el.innerHTML='<i class="bi bi-people"></i> 이전 선발자: <strong>없음</strong> &nbsp;<span class="text-muted">(중복 선발 방지 비활성)</span>';
    el.className='text-secondary small py-1';
  } else {
    el.innerHTML='<i class="bi bi-person-x-fill text-danger"></i> 이전 선발자 <strong>'+s.size+'명</strong>이 이번 선발에서 자동 제외됩니다.';
    el.className='text-warning-emphasis small py-1 fw-semibold';
  }
  if(btn)btn.classList.toggle('d-none',s.size===0);
}
updateExcludeUI();
</script>
</body>
</html>"""

# ──────────────────────────────────────────────────────────────────────
# Flask 앱 설정
# ──────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/api/upload", methods=["OPTIONS"])
@app.route("/api/demo",   methods=["OPTIONS"])
def _preflight():
    return "", 204

@app.route("/")
def serve_index():
    """프론트엔드 HTML 반환 — 파일 시스템 없이 메모리에서 직접 서빙"""
    return _INDEX_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}

# ──────────────────────────────────────────────────────────────────────
# 로깅 (투명성 원칙)
# ──────────────────────────────────────────────────────────────────────
_log_buf = io.StringIO()
_handler = logging.StreamHandler(_log_buf)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logger = logging.getLogger("hanyang_api")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_handler)

def _flush_log() -> str:
    content = _log_buf.getvalue()
    _log_buf.truncate(0); _log_buf.seek(0)
    return content

# ──────────────────────────────────────────────────────────────────────
# 전역 상수
# ──────────────────────────────────────────────────────────────────────
GRADE_SCORES: Dict[int, int] = {4: 50, 3: 35, 2: 20, 1: 5}
MAX_SCHOLARS: int = 50
DEFAULT_GRAD_CREDITS: float = 120.0

STEM_KEYWORDS = ["공학","이학","전자","기계","컴퓨터","소프트웨어","정보","국방","방산","항공","우주","화학","물리","수학","전기","통신","로봇","자동화","반도체","에너지","재료","토목","건축","환경","생명","바이오","인공지능","AI","데이터","사이버","보안","국방공학","방위산업","드론","무기체계","레이더","탄약"]
CERT_KEYWORDS = ["국가기술자격","국가전문자격","기사","산업기사","기능사","기능장","기술사","TOEIC","TOEFL","IELTS","OPIc","JLPT","HSK","토익","토플","오픽","텝스","TEPS","자격증","면허","어학성적"]
VOLUNTEER_KEYWORDS = ["봉사","자원봉사","사회봉사","봉사활동","봉사시간"]
MILITARY_KEYWORDS  = ["병역","현역","예비역","만기전역","군필","복무완료","전역","군복무"]
DOC_ELIGIBILITY_KW = ["자립지원 대상자 확인서","자립지원대상자확인서","자립준비청년 확인서"]
DOC_ENROLLMENT_KW  = ["재학증명서","재학 증명서"]
DOC_TRANSCRIPT_KW  = ["성적증명서","성적표","학업성적","성적 증명서"]

# ──────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ApplicantData:
    applicant_key: str = ""; name: str = "미확인"; grade: int = 0; major: str = ""
    completed_credits: float = 0.0; graduation_credits: float = DEFAULT_GRAD_CREDITS
    gpa: float = 0.0; has_certificate: bool = False; volunteer_hours: float = 0.0
    is_military: bool = False; is_eligible: bool = False; has_enrollment: bool = False
    has_transcript: bool = False; has_bonus_doc: bool = False
    raw_texts: Dict[str, str] = field(default_factory=dict)
    parse_notes: List[str] = field(default_factory=list)
    grade_score: float = 0.0; completion_rate: float = 0.0; completion_score: float = 0.0
    bonus_stem: bool = False; bonus_cert: bool = False; bonus_volunteer: bool = False
    bonus_score: float = 0.0; total_score: float = 0.0

# ──────────────────────────────────────────────────────────────────────
# 민감 정보 마스킹
# ──────────────────────────────────────────────────────────────────────
def mask_sensitive(text: str) -> str:
    text = re.sub(r"(\d{6})\s*[-–]\s*(\d{7})", r"\1-*******", text)
    text = re.sub(r"(\d{6})(\d{7})", r"\1*******", text)
    text = re.sub(r"(01\d)\s*[-–]\s*(\d{3,4})\s*[-–]\s*(\d{4})", r"\1-****-\3", text)
    return text

# ──────────────────────────────────────────────────────────────────────
# PDF 파서
# ──────────────────────────────────────────────────────────────────────
class PDFParser:
    @staticmethod
    def extract_text(pdf_bytes: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages  = [page.extract_text() or "" for page in reader.pages]
            return mask_sensitive("\n".join(pages))
        except Exception as e:
            logger.warning(f"PDF 추출 실패: {e}"); return ""

    @staticmethod
    def classify(text: str) -> str:
        if any(k in text for k in DOC_ELIGIBILITY_KW): return "eligibility"
        if any(k in text for k in DOC_ENROLLMENT_KW):  return "enrollment"
        if any(k in text for k in DOC_TRANSCRIPT_KW):  return "transcript"
        if any(k in text for k in CERT_KEYWORDS+VOLUNTEER_KEYWORDS+MILITARY_KEYWORDS): return "bonus"
        return "unknown"

    @staticmethod
    def extract_name(text: str) -> Optional[str]:
        for p in [r"성\s*명\s*[：:]\s*([가-힣]{2,5})",r"이\s*름\s*[：:]\s*([가-힣]{2,5})",r"학생명\s*[：:]\s*([가-힣]{2,5})"]:
            m=re.search(p,text)
            if m: return m.group(1).strip()
        return None

    @staticmethod
    def extract_grade(text: str) -> Optional[int]:
        for p in [r"([1-4])\s*학년",r"학\s*년\s*[：:\s]*([1-4])"]:
            m=re.search(p,text)
            if m:
                g=int(m.group(1))
                if 1<=g<=4: return g
        return None

    @staticmethod
    def extract_major(text: str) -> Optional[str]:
        for p in [r"전\s*공\s*[：:\s]+([^\n\r\t]{2,30})",r"학\s*과\s*[：:\s]+([^\n\r\t]{2,30})",r"학\s*부\s*[：:\s]+([^\n\r\t]{2,30})"]:
            m=re.search(p,text)
            if m:
                v=re.sub(r"\s+"," ",m.group(1)).strip()
                if 2<=len(v)<=40: return v
        return None

    @staticmethod
    def extract_credits(text: str) -> Tuple[Optional[float], Optional[float]]:
        grad=None
        for p in [r"졸업\s*기준\s*학점\s*[：:\s]*(\d+\.?\d*)",r"졸업\s*이수\s*학점\s*[：:\s]*(\d+\.?\d*)",r"졸업\s*학점\s*[：:\s]*(\d+\.?\d*)"]:
            m=re.search(p,text)
            if m: grad=float(m.group(1)); break
        comp=None
        for p in [r"취득\s*학점\s*[：:\s]*(\d+\.?\d*)",r"이수\s*학점\s*[：:\s]*(\d+\.?\d*)",r"누적\s*학점\s*[：:\s]*(\d+\.?\d*)"]:
            m=re.search(p,text)
            if m: comp=float(m.group(1)); break
        return comp, grad

    @staticmethod
    def extract_gpa(text: str) -> Optional[float]:
        for p in [r"전체\s*평점\s*[：:\s]*(\d+\.\d+)",r"누적\s*평점\s*[：:\s]*(\d+\.\d+)",r"평\s*점\s*[：:\s]*(\d+\.\d+)",r"GPA\s*[：:\s]*(\d+\.\d+)"]:
            m=re.search(p,text,re.IGNORECASE)
            if m:
                v=float(m.group(1))
                if 0.0<=v<=4.5: return v
        return None

    @staticmethod
    def check_certificate(text: str) -> bool:
        return any(k.lower() in text.lower() for k in CERT_KEYWORDS)

    @staticmethod
    def extract_volunteer_hours(text: str) -> float:
        for p in [r"봉사\s*시간\s*[：:\s]*(\d+\.?\d*)",r"총\s*봉사\s*[：:\s]*(\d+\.?\d*)\s*시간",r"(\d+\.?\d*)\s*시간"]:
            ms=re.findall(p,text)
            if ms:
                h=max(float(x) for x in ms)
                if 0<h<10000: return h
        return 0.0

    @staticmethod
    def check_military(text: str) -> bool:
        return any(k in text for k in MILITARY_KEYWORDS)

# ──────────────────────────────────────────────────────────────────────
# 점수 계산 엔진
# ──────────────────────────────────────────────────────────────────────
class ScoringEngine:
    @staticmethod
    def calculate(a: ApplicantData) -> ApplicantData:
        a.grade_score = float(GRADE_SCORES.get(a.grade, 0))
        if a.graduation_credits > 0:
            rate = min(a.completed_credits / a.graduation_credits, 1.0)
            a.completion_rate = rate; a.completion_score = round(rate*50, 2)
        bonus = 0
        a.bonus_stem     = any(k in a.major for k in STEM_KEYWORDS)
        a.bonus_cert     = a.has_certificate
        a.bonus_volunteer = a.volunteer_hours >= 50.0
        if a.bonus_stem:      bonus += 5
        if a.bonus_cert:      bonus += 3
        if a.bonus_volunteer: bonus += 2
        a.bonus_score = float(min(bonus, 10))
        a.total_score = round(a.grade_score + a.completion_score + a.bonus_score, 2)
        return a

# ──────────────────────────────────────────────────────────────────────
# ZIP 처리기
# ──────────────────────────────────────────────────────────────────────
class DocumentProcessor:
    def __init__(self): self._p=PDFParser(); self._s=ScoringEngine()

    def process(self, zip_bytes: bytes) -> List[ApplicantData]:
        applicants: Dict[str, ApplicantData] = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for fp in zf.namelist():
                if not fp.lower().endswith(".pdf") or "__MACOSX" in fp: continue
                key = self._key(fp)
                if key not in applicants: applicants[key]=ApplicantData(applicant_key=key,name=key)
                a = applicants[key]
                try:
                    text = self._p.extract_text(zf.read(fp))
                    if not text.strip(): a.parse_notes.append(f"⚠ '{fp}': 텍스트 추출 불가"); continue
                    dt = self._p.classify(text)
                    a.raw_texts[dt] = a.raw_texts.get(dt,"") + "\n" + text
                    self._apply(a, dt, text)
                except Exception as e:
                    a.parse_notes.append(f"❌ '{fp}': {e}")

        for a in applicants.values():
            for text in a.raw_texts.values():
                name=self._p.extract_name(text)
                if name: a.name=name; break

        results=[]
        for a in applicants.values():
            if not a.is_eligible: a.parse_notes.insert(0,"⛔ 자립지원 대상자 확인서 미확인 — 제외")
            self._s.calculate(a); results.append(a)
        return results

    @staticmethod
    def _key(fp: str) -> str:
        parts=fp.replace("\\","/").split("/")
        if len(parts)>=2: return parts[0].strip()
        base=os.path.splitext(parts[0])[0]
        for sep in ("_","-"," "):
            if sep in base: return base.split(sep)[0].strip()
        return base.strip()

    def _apply(self, a: ApplicantData, dt: str, text: str):
        p=self._p
        if dt=="eligibility": a.is_eligible=True
        elif dt=="enrollment":
            a.has_enrollment=True
            g=p.extract_grade(text); a.grade=g if g else a.grade
            m=p.extract_major(text); a.major=m if m else a.major
        elif dt=="transcript":
            a.has_transcript=True
            comp,grad=p.extract_credits(text)
            if comp is not None: a.completed_credits=comp
            if grad is not None: a.graduation_credits=grad
            gpa=p.extract_gpa(text)
            if gpa is not None: a.gpa=gpa
            if a.grade==0:
                g=p.extract_grade(text)
                if g: a.grade=g
            if not a.major:
                m=p.extract_major(text)
                if m: a.major=m
        elif dt=="bonus":
            a.has_bonus_doc=True
            if p.check_certificate(text): a.has_certificate=True
            h=p.extract_volunteer_hours(text)
            if h>0: a.volunteer_hours=max(a.volunteer_hours,h)
            if p.check_military(text): a.is_military=True
        else:
            if any(k in text for k in DOC_ELIGIBILITY_KW): a.is_eligible=True
            if a.grade==0:
                g=p.extract_grade(text)
                if g: a.grade=g
            if not a.major:
                m=p.extract_major(text)
                if m: a.major=m
            comp,grad=p.extract_credits(text)
            if comp and a.completed_credits==0: a.completed_credits=comp
            if grad: a.graduation_credits=grad
            gpa=p.extract_gpa(text)
            if gpa and a.gpa==0: a.gpa=gpa
            if p.check_certificate(text): a.has_certificate=True
            h=p.extract_volunteer_hours(text)
            if h>0: a.volunteer_hours=max(a.volunteer_hours,h)
            if p.check_military(text): a.is_military=True

# ──────────────────────────────────────────────────────────────────────
# 선발 함수
# ──────────────────────────────────────────────────────────────────────
def select_scholars(applicants: List[ApplicantData], n: int=MAX_SCHOLARS, excluded: set=None) -> Tuple[List[Dict],List[Dict]]:
    excluded = excluded or set()
    for a in applicants:
        if a.name in excluded:
            a.parse_notes.insert(0, "⛔ 이전 선발자 — 중복 선발 제외")
    eligible=[a for a in applicants if a.is_eligible and a.name not in excluded]
    if not eligible: return [],[]
    records=[]
    for a in eligible:
        records.append({"성명":a.name,"학년":f"{a.grade}학년" if a.grade>0 else "미확인","_학년숫자":a.grade,
            "전공":a.major or "미확인","이수학점":a.completed_credits,"졸업기준학점":a.graduation_credits,
            "이수율":round(a.completion_rate*100,1),"_이수율정렬":a.completion_rate,"GPA":a.gpa,
            "학년점수":a.grade_score,"이수율점수":a.completion_score,"가산점":a.bonus_score,"총점":a.total_score,
            "이공계방산":"✓" if a.bonus_stem else "","자격증어학":"✓" if a.bonus_cert else "","봉사50h":"✓" if a.bonus_volunteer else "",
            "자립확인서":"✓","재학증명서":"✓" if a.has_enrollment else "미확인","성적증명서":"✓" if a.has_transcript else "미확인",
            "비고":" | ".join(a.parse_notes) if a.parse_notes else "정상 처리"})
    records.sort(key=lambda r:(r["총점"],r["_이수율정렬"],r["_학년숫자"],r["GPA"]),reverse=True)
    all_list=[]
    for rank,rec in enumerate(records,1):
        rec["순위"]=rank; rec.pop("_학년숫자",None); rec.pop("_이수율정렬",None); all_list.append(rec)
    return all_list[:n], all_list

def build_report(selected: List[Dict], total: int) -> Dict[str,Any]:
    if not selected: return {}
    n=len(selected); scores=[r["총점"] for r in selected]; comp=[r["이수율"] for r in selected]; gpas=[r["GPA"] for r in selected]
    gd: Dict[str,int]={}
    for r in selected: gd[r["학년"]]=gd.get(r["학년"],0)+1
    stem=sum(1 for r in selected if r["이공계방산"]=="✓")
    cert=sum(1 for r in selected if r["자격증어학"]=="✓")
    vol =sum(1 for r in selected if r["봉사50h"]=="✓")
    return {"total_applicants":total,"selected_count":n,"selection_rate":round(n/total*100,1) if total else 0,
            "avg_score":round(sum(scores)/n,2),"max_score":round(max(scores),2),"min_score":round(min(scores),2),
            "avg_completion":round(sum(comp)/n,1),"avg_gpa":round(sum(gpas)/n,2),"grade_dist":gd,
            "stem_count":stem,"stem_rate":round(stem/n*100,1),"cert_count":cert,"vol_count":vol}

def make_demo_applicants(n: int=30) -> List[ApplicantData]:
    random.seed(42)
    names=["김민준","이서연","박도윤","최서현","정예은","강지호","조수아","윤민서","장하은","임준혁","오지원","한소율","신재현","권나연","유태양","배수빈","노현우","심지유","문성민","허다은","서지훈","안채원","남기태","고은서","류민호","전수현","양준서","설아린","마지현","제갈민"]
    majors=["컴퓨터공학과","전자공학과","기계공학과","국방학과","경영학과","사회복지학과","심리학과","소프트웨어학과","방위산업학과","화학공학과"]
    results=[]
    for i in range(n):
        a=ApplicantData(applicant_key=f"demo_{i}",name=names[i%len(names)],grade=random.randint(1,4),
            major=majors[random.randint(0,len(majors)-1)],completed_credits=round(random.uniform(10,135),1),
            graduation_credits=random.choice([120.0,130.0,140.0]),gpa=round(random.uniform(1.5,4.3),2),
            has_certificate=random.random()>0.5,volunteer_hours=random.choice([0,20,55,80,100]),
            is_eligible=random.random()>0.1,has_enrollment=True,has_transcript=True)
        ScoringEngine.calculate(a); results.append(a)
    return results

def _clean(obj: Any) -> Any:
    if isinstance(obj,float) and (math.isnan(obj) or math.isinf(obj)): return None
    if isinstance(obj,dict): return {k:_clean(v) for k,v in obj.items()}
    if isinstance(obj,list): return [_clean(v) for v in obj]
    return obj

# ──────────────────────────────────────────────────────────────────────
# API 엔드포인트
# ──────────────────────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
def upload_zip():
    _flush_log()
    if "file" not in request.files: return jsonify({"success":False,"error":"파일이 없습니다."}),400
    f=request.files["file"]
    if not f.filename.lower().endswith(".zip"): return jsonify({"success":False,"error":"ZIP 파일만 허용됩니다."}),400
    try:
        zb=f.read()
        if not zipfile.is_zipfile(io.BytesIO(zb)): return jsonify({"success":False,"error":"손상된 ZIP 파일입니다."}),400
        applics=DocumentProcessor().process(zb)
        if not applics: return jsonify({"success":False,"error":"처리 가능한 신청자가 없습니다."}),400
        try: excl=set(json.loads(request.form.get("excluded_names","[]")))
        except Exception: excl=set()
        sel,all_el=select_scholars(applics,MAX_SCHOLARS,excl)
        return jsonify(_clean({"success":True,"is_demo":False,"total_applicants":len(applics),"eligible_count":len(all_el),
            "selected_count":len(sel),"results":sel,"all_results":all_el,"stats":build_report(sel,len(applics)),
            "warnings":[{"name":a.name,"note":" | ".join(a.parse_notes)} for a in applics if a.parse_notes],
            "log":_flush_log()}))
    except MemoryError: return jsonify({"success":False,"error":"파일이 너무 큽니다."}),413
    except Exception as e: return jsonify({"success":False,"error":str(e)}),500

@app.route("/api/demo", methods=["POST"])
def demo():
    _flush_log()
    try:
        applics=make_demo_applicants(30)
        sel,all_el=select_scholars(applics,MAX_SCHOLARS)
        return jsonify(_clean({"success":True,"is_demo":True,"total_applicants":len(applics),"eligible_count":len(all_el),
            "selected_count":len(sel),"results":sel,"all_results":all_el,"stats":build_report(sel,len(applics)),
            "warnings":[],"log":_flush_log()}))
    except Exception as e: return jsonify({"success":False,"error":str(e)}),500

@app.route("/api/health")
def health():
    return jsonify({"status":"ok","timestamp":datetime.now().isoformat()})
