/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

/**
 * 验证档案 — 交叉验证结果展示
 * 展示冲突检测、交叉验证结果、事实置信度评分
 */

import { CheckCircleOutlined, WarningOutlined, CloseCircleOutlined, InfoCircleOutlined, TrophyOutlined } from '@ant-design/icons'
import styles from './index.module.scss'

interface Conflict {
  fact_a?: string
  fact_b?: string
  conflict_type?: string   // numerical / qualitative
  severity?: string        // critical / major / minor
  difference_ratio?: number
  source_a?: string
  source_b?: string
}

interface ConfidenceScore {
  source_authority?: number
  cross_validation?: number
  timeliness?: number
  specificity?: number
  overall_score?: number
  source_name?: string
  source_url?: string
  content?: string
}

interface ValidationEntry {
  fact?: string
  confidence_score?: number
  confidence_breakdown?: ConfidenceScore
}

interface ConflictReport {
  conflicts_detected?: number
  conflicts?: Conflict[]
  validation_results?: Record<string, unknown>
  confidence_scores?: Record<string, ConfidenceScore>
}

interface VerificationArchiveProps {
  report: ConflictReport | null
}

const severityConfig: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
  critical: { icon: <CloseCircleOutlined />, label: '严重', color: '#ff4d4f' },
  major: { icon: <WarningOutlined />, label: '重要', color: '#faad14' },
  minor: { icon: <InfoCircleOutlined />, label: '轻微', color: '#1677ff' },
}

const conflictTypeLabels: Record<string, string> = {
  numerical: '数值矛盾',
  qualitative: '结论方向矛盾',
}

function getConfidenceBadge(score: number) {
  if (score >= 0.8) return { color: '#52c41a', label: '高可信', icon: <CheckCircleOutlined /> }
  if (score >= 0.6) return { color: '#faad14', label: '中可信', icon: <InfoCircleOutlined /> }
  return { color: '#ff4d4f', label: '低可信', icon: <CloseCircleOutlined /> }
}

export default function VerificationArchive({ report }: VerificationArchiveProps) {
  if (!report || (!report.conflicts_detected && !report.confidence_scores)) {
    return (
      <div className={styles['verification-empty']}>
        <InfoCircleOutlined style={{ fontSize: 24, color: '#8c8c8c' }} />
        <p>本次研究未检测到数据冲突</p>
        <p className={styles['verification-empty-sub']}>所有引用来源一致，结论可信</p>
      </div>
    )
  }

  const conflicts = report.conflicts || []
  const resolvedCount = conflicts.filter(c => (c as any).resolved).length
  const confidenceScores = Object.entries(report.confidence_scores || {})

  return (
    <div className={styles['verification-archive']}>
      {/* 摘要卡片 */}
      <div className={styles['va-summary']}>
        <div className={styles['va-summary-item']}>
          <div className={styles['va-summary-value']}>{report.conflicts_detected || 0}</div>
          <div className={styles['va-summary-label']}>检测到冲突</div>
        </div>
        <div className={styles['va-summary-item']}>
          <div className={styles['va-summary-value']}>{resolvedCount}</div>
          <div className={styles['va-summary-label']}>已解决</div>
        </div>
        <div className={styles['va-summary-item']}>
          <div className={styles['va-summary-value']}>{confidenceScores.length}</div>
          <div className={styles['va-summary-label']}>事实评分</div>
        </div>
        {confidenceScores.length > 0 && (
          <div className={styles['va-summary-item']}>
            <div className={styles['va-summary-value']}>
              {(confidenceScores.reduce((sum, [, v]) => sum + (v.overall_score || 0), 0) / confidenceScores.length).toFixed(2)}
            </div>
            <div className={styles['va-summary-label']}>平均置信度</div>
          </div>
        )}
      </div>

      {/* 冲突详情 */}
      {conflicts.length > 0 && (
        <section className={styles['va-section']}>
          <h4 className={styles['va-section-title']}>
            <WarningOutlined /> 冲突详情
          </h4>
          {conflicts.map((conflict, idx) => {
            const sev = severityConfig[conflict.severity || 'minor']
            return (
              <div key={idx} className={styles['va-conflict-card']}>
                <div className={styles['va-conflict-header']}>
                  <span className={styles['va-conflict-severity']} style={{ color: sev.color }}>
                    {sev.icon} {sev.label}
                  </span>
                  <span className={styles['va-conflict-type']}>
                    {conflictTypeLabels[conflict.conflict_type || ''] || conflict.conflict_type}
                  </span>
                  <span className={styles['va-conflict-resolved']}>
                    {(conflict as any).resolved ? (
                      <CheckCircleOutlined style={{ color: '#52c41a' }} /> 已解决
                    ) : (
                      <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> 未解决
                    )}
                  </span>
                </div>
                <div className={styles['va-conflict-body']}>
                  <div className={styles['va-conflict-pair']}>
                    <div className={styles['va-conflict-fact']}>
                      <span className={styles['va-conflict-label']}>事实 A</span>
                      <p>{conflict.fact_a || 'N/A'}</p>
                      {conflict.source_a && <span className={styles['va-conflict-source']}>来源: {conflict.source_a}</span>}
                    </div>
                    <div className={styles['va-conflict-vs']}>vs</div>
                    <div className={styles['va-conflict-fact']}>
                      <span className={styles['va-conflict-label']}>事实 B</span>
                      <p>{conflict.fact_b || 'N/A'}</p>
                      {conflict.source_b && <span className={styles['va-conflict-source']}>来源: {conflict.source_b}</span>}
                    </div>
                  </div>
                  {conflict.difference_ratio && (
                    <div className={styles['va-conflict-diff']}>
                      差异倍数: {conflict.difference_ratio.toFixed(1)}x
                    </div>
                  )}
                  {(conflict as any).resolution && (
                    <div className={styles['va-conflict-resolution']}>
                      <TrophyOutlined style={{ color: '#52c41a' }} /> 验证结论: {(conflict as any).resolution}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </section>
      )}

      {/* 事实置信度评分 */}
      {confidenceScores.length > 0 && (
        <section className={styles['va-section']}>
          <h4 className={styles['va-section-title']}>
            <TrophyOutlined /> 事实置信度评分
          </h4>
          {confidenceScores.slice(0, 20).map(([factId, score]) => {
            const badge = getConfidenceBadge(score.overall_score || 0)
            return (
              <div key={factId} className={styles['va-score-card']}>
                <div className={styles['va-score-header']}>
                  <span className={styles['va-score-badge']} style={{ color: badge.color }}>
                    {badge.icon} {badge.label}
                  </span>
                  <span className={styles['va-score-value']}>
                    {(score.overall_score || 0).toFixed(2)}
                  </span>
                </div>
                {score.content && (
                  <p className={styles['va-score-content']}>
                    {score.content.length > 120 ? score.content.slice(0, 120) + '...' : score.content}
                  </p>
                )}
                <div className={styles['va-score-breakdown']}>
                  {score.source_authority != null && (
                    <div className={styles['va-score-dim']}>
                      <span>权威性</span>
                      <div className={styles['va-score-bar']}>
                        <div className={styles['va-score-bar-fill']} style={{ width: `${(score.source_authority) * 100}%` }} />
                      </div>
                      <span>{score.source_authority.toFixed(2)}</span>
                    </div>
                  )}
                  {score.cross_validation != null && (
                    <div className={styles['va-score-dim']}>
                      <span>交叉验证</span>
                      <div className={styles['va-score-bar']}>
                        <div className={styles['va-score-bar-fill']} style={{ width: `${(score.cross_validation) * 100}%` }} />
                      </div>
                      <span>{score.cross_validation.toFixed(2)}</span>
                    </div>
                  )}
                  {score.timeliness != null && (
                    <div className={styles['va-score-dim']}>
                      <span>时效性</span>
                      <div className={styles['va-score-bar']}>
                        <div className={styles['va-score-bar-fill']} style={{ width: `${(score.timeliness) * 100}%` }} />
                      </div>
                      <span>{score.timeliness.toFixed(2)}</span>
                    </div>
                  )}
                  {score.specificity != null && (
                    <div className={styles['va-score-dim']}>
                      <span>具体度</span>
                      <div className={styles['va-score-bar']}>
                        <div className={styles['va-score-bar-fill']} style={{ width: `${(score.specificity) * 100}%` }} />
                      </div>
                      <span>{score.specificity.toFixed(2)}</span>
                    </div>
                  )}
                </div>
                {score.source_name && (
                  <div className={styles['va-score-source']}>
                    来源: {score.source_name}
                    {score.source_url && (
                      <a href={score.source_url} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 8 }}>
                        查看原文 →
                      </a>
                    )}
                  </div>
                )}
              </div>
            )
          })}
          {confidenceScores.length > 20 && (
            <div className={styles['va-more-hint']}>
              共 {confidenceScores.length} 条事实，此处展示前 20 条
            </div>
          )}
        </section>
      )}
    </div>
  )
}
