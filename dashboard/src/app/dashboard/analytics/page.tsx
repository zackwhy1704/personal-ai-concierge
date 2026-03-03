'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export default function AnalyticsPage() {
  const [dashboard, setDashboard] = useState<Record<string, unknown> | null>(null)
  const [productPerf, setProductPerf] = useState<Array<Record<string, unknown>>>([])
  const [strategyPerf, setStrategyPerf] = useState<Array<Record<string, unknown>>>([])
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [analysisResult, setAnalysisResult] = useState<Record<string, unknown> | null>(null)
  const [optimizeResult, setOptimizeResult] = useState<Record<string, unknown> | null>(null)

  useEffect(() => { loadData() }, [])

  async function loadData() {
    try {
      const [dash, prods, strats] = await Promise.all([
        api.getSalesDashboard().catch(() => null),
        api.getProductPerformance().catch(() => ({})),
        api.getStrategyPerformance().catch(() => ({})),
      ])
      setDashboard(dash)

      // Handle both array and object responses
      if (Array.isArray(prods)) {
        setProductPerf(prods)
      } else {
        const prodData = prods as Record<string, unknown>
        setProductPerf((prodData.products || prodData.data || []) as Array<Record<string, unknown>>)
      }

      if (Array.isArray(strats)) {
        setStrategyPerf(strats)
      } else {
        const stratData = strats as Record<string, unknown>
        setStrategyPerf((stratData.strategies || stratData.data || []) as Array<Record<string, unknown>>)
      }
    } catch (err) {
      console.error('Failed to load analytics:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleAnalyze() {
    setAnalyzing(true)
    setAnalysisResult(null)
    try {
      const result = await api.analyzeLearning()
      setAnalysisResult(result as Record<string, unknown>)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setAnalyzing(false)
    }
  }

  async function handleOptimize() {
    if (!confirm('This will auto-adjust strategy weights based on performance data. Continue?')) return
    setOptimizing(true)
    setOptimizeResult(null)
    try {
      const result = await api.optimizeLearning()
      setOptimizeResult(result as Record<string, unknown>)
      loadData()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Optimization failed')
    } finally {
      setOptimizing(false)
    }
  }

  if (loading) return <div className="text-gray-500">Loading analytics...</div>

  const funnel = (dashboard?.funnel || {}) as Record<string, unknown>
  const revenue = (dashboard?.revenue || {}) as Record<string, unknown>

  const totalAttempts = Number(funnel.total_attempts || funnel.presented || 0)
  const totalInterest = Number(funnel.interest_shown || 0)
  const totalClicks = Number(funnel.clicked || funnel.total_clicks || 0)
  const totalConversions = Number(funnel.converted || funnel.total_conversions || 0)
  const totalRevenue = Number(revenue.total || revenue.total_revenue || 0)
  const conversionRate = totalAttempts > 0 ? ((totalConversions / totalAttempts) * 100) : 0

  return (
    <div className="max-w-5xl">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Sales Analytics</h1>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Revenue" value={`$${totalRevenue.toFixed(2)}`} subtitle="attributed to bot" />
        <StatCard label="Conversion Rate" value={`${conversionRate.toFixed(1)}%`} subtitle={`${totalConversions} of ${totalAttempts} attempts`} />
        <StatCard label="Upsell Attempts" value={String(totalAttempts)} subtitle="products presented" />
        <StatCard label="Interest Shown" value={String(totalInterest)} subtitle="guests engaged" />
      </div>

      {/* Conversion Funnel */}
      <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Conversion Funnel</h2>
        {totalAttempts > 0 ? (
          <div className="space-y-4">
            <FunnelBar label="Presented" value={totalAttempts} max={totalAttempts} color="bg-blue-500" />
            <FunnelBar label="Interest Shown" value={totalInterest} max={totalAttempts} color="bg-indigo-500" />
            <FunnelBar label="Clicked" value={totalClicks} max={totalAttempts} color="bg-purple-500" />
            <FunnelBar label="Converted" value={totalConversions} max={totalAttempts} color="bg-green-500" />
          </div>
        ) : (
          <p className="text-gray-500 text-sm">No upsell data yet. Upsell attempts will appear here once the bot starts presenting products to guests.</p>
        )}
      </div>

      {/* Product Performance */}
      <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Product Performance</h2>
        {productPerf.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-3 text-gray-500 font-medium">Product</th>
                  <th className="text-right py-2 px-3 text-gray-500 font-medium">Presented</th>
                  <th className="text-right py-2 px-3 text-gray-500 font-medium">Conversions</th>
                  <th className="text-right py-2 px-3 text-gray-500 font-medium">Revenue</th>
                  <th className="text-right py-2 px-3 text-gray-500 font-medium">Conv. Rate</th>
                </tr>
              </thead>
              <tbody>
                {productPerf.map((p, i) => {
                  const presented = Number(p.presented || p.attempts || 0)
                  const conversions = Number(p.conversions || p.converted || 0)
                  const rev = Number(p.revenue || 0)
                  const rate = presented > 0 ? ((conversions / presented) * 100) : 0
                  return (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-2 px-3 font-medium">{String(p.name || p.product_name || '')}</td>
                      <td className="py-2 px-3 text-right">{presented}</td>
                      <td className="py-2 px-3 text-right">{conversions}</td>
                      <td className="py-2 px-3 text-right text-green-700">${rev.toFixed(2)}</td>
                      <td className="py-2 px-3 text-right">{rate.toFixed(1)}%</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-sm">No product performance data yet.</p>
        )}
      </div>

      {/* Strategy Performance */}
      <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Strategy Performance</h2>
        {strategyPerf.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-3 text-gray-500 font-medium">Strategy</th>
                  <th className="text-left py-2 px-3 text-gray-500 font-medium">Type</th>
                  <th className="text-right py-2 px-3 text-gray-500 font-medium">Attempts</th>
                  <th className="text-right py-2 px-3 text-gray-500 font-medium">Conversions</th>
                  <th className="text-right py-2 px-3 text-gray-500 font-medium">Revenue</th>
                  <th className="text-right py-2 px-3 text-gray-500 font-medium">Conv. Rate</th>
                </tr>
              </thead>
              <tbody>
                {strategyPerf.map((s, i) => {
                  const attempts = Number(s.attempts || s.total_attempts || 0)
                  const conversions = Number(s.conversions || s.total_conversions || 0)
                  const rev = Number(s.revenue || s.total_revenue || 0)
                  const rate = attempts > 0 ? ((conversions / attempts) * 100) : 0
                  const triggerType = String(s.trigger_type || '')
                  const triggerColors: Record<string, string> = {
                    keyword: 'bg-blue-100 text-blue-700',
                    intent_match: 'bg-purple-100 text-purple-700',
                    category_context: 'bg-green-100 text-green-700',
                    proactive: 'bg-yellow-100 text-yellow-700',
                    cross_sell: 'bg-orange-100 text-orange-700',
                  }
                  return (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-2 px-3 font-medium">{String(s.name || s.strategy_name || '')}</td>
                      <td className="py-2 px-3">
                        {triggerType && (
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${triggerColors[triggerType] || 'bg-gray-100'}`}>
                            {triggerType.replace('_', ' ')}
                          </span>
                        )}
                      </td>
                      <td className="py-2 px-3 text-right">{attempts}</td>
                      <td className="py-2 px-3 text-right">{conversions}</td>
                      <td className="py-2 px-3 text-right text-green-700">${rev.toFixed(2)}</td>
                      <td className="py-2 px-3 text-right">{rate.toFixed(1)}%</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-sm">No strategy performance data yet.</p>
        )}
      </div>

      {/* Learning & Optimization */}
      <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Learning & Optimization</h2>
        <p className="text-sm text-gray-500 mb-4">
          The AI learning engine analyzes conversion patterns and auto-adjusts strategy weights to improve performance over time.
        </p>
        <div className="flex gap-3">
          <button onClick={handleAnalyze} disabled={analyzing}
            className="px-4 py-2 bg-gray-800 text-white rounded-lg text-sm hover:bg-gray-900 disabled:opacity-50">
            {analyzing ? 'Analyzing...' : 'Analyze Performance'}
          </button>
          <button onClick={handleOptimize} disabled={optimizing}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
            {optimizing ? 'Optimizing...' : 'Run Optimization'}
          </button>
        </div>

        {analysisResult && (
          <div className="mt-4 p-4 bg-gray-50 rounded-lg">
            <h4 className="font-medium text-gray-700 mb-2">Analysis Results</h4>
            <div className="text-sm text-gray-600 space-y-1">
              {renderAnalysisResults(analysisResult)}
            </div>
          </div>
        )}

        {optimizeResult && (
          <div className="mt-4 p-4 bg-green-50 rounded-lg">
            <h4 className="font-medium text-green-700 mb-2">Optimization Complete</h4>
            <div className="text-sm text-green-600 space-y-1">
              {renderOptimizeResults(optimizeResult)}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Helper Components ─────────────────────────────────────────────────────

function StatCard({ label, value, subtitle }: { label: string; value: string; subtitle: string }) {
  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold text-gray-800 mt-1">{value}</p>
      <p className="text-xs text-gray-400 mt-1">{subtitle}</p>
    </div>
  )
}

function FunnelBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-600">{label}</span>
        <span className="font-medium text-gray-800">{value} <span className="text-gray-400 text-xs">({pct.toFixed(1)}%)</span></span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-4">
        <div className={`h-4 rounded-full ${color} transition-all duration-500`}
          style={{ width: `${Math.max(pct, 1)}%` }} />
      </div>
    </div>
  )
}

function renderAnalysisResults(data: Record<string, unknown>): React.ReactNode {
  const items: string[] = []

  if (data.recommendations) {
    const recs = data.recommendations as Record<string, unknown>
    if (Array.isArray(recs)) {
      recs.forEach((r: unknown) => items.push(String(r)))
    } else if (typeof recs === 'object') {
      Object.entries(recs).forEach(([key, value]) => {
        if (Array.isArray(value)) {
          value.forEach((v: unknown) => items.push(String(v)))
        } else {
          items.push(`${key}: ${JSON.stringify(value)}`)
        }
      })
    }
  }

  if (data.performance) {
    const perf = data.performance as Record<string, unknown>
    Object.entries(perf).forEach(([key, value]) => {
      items.push(`${key.replace(/_/g, ' ')}: ${typeof value === 'number' ? value.toFixed(2) : JSON.stringify(value)}`)
    })
  }

  if (items.length === 0) {
    items.push(JSON.stringify(data, null, 2))
  }

  return items.map((item, i) => <p key={i}>{item}</p>)
}

function renderOptimizeResults(data: Record<string, unknown>): React.ReactNode {
  const items: string[] = []

  const adjustments = (data.strategy_adjustments || []) as Array<Record<string, unknown>>
  adjustments.forEach(a => {
    items.push(`Strategy "${a.name || a.strategy_name}": priority ${a.old_priority || '?'} → ${a.new_priority || a.priority || '?'}`)
  })

  const crossSell = (data.cross_sell_discoveries || []) as Array<Record<string, unknown>>
  crossSell.forEach(c => {
    items.push(`Cross-sell discovered: ${c.product_a || c.category_a} ↔ ${c.product_b || c.category_b}`)
  })

  const abTests = (data.ab_test_results || []) as Array<Record<string, unknown>>
  abTests.forEach(t => {
    items.push(`A/B test: "${t.winner || t.group}" won (${t.confidence || '?'}% confidence)`)
  })

  if (items.length === 0) {
    items.push('Optimization completed. No adjustments needed at this time.')
  }

  return items.map((item, i) => <p key={i}>{item}</p>)
}
