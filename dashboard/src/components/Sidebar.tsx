'use client'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

interface NavGroup {
  label: string
  items: { href: string; label: string }[]
}

const tenantNav: NavGroup[] = [
  {
    label: 'Setup',
    items: [
      { href: '/dashboard', label: 'Overview' },
      { href: '/dashboard/guardrails', label: 'Guardrails' },
      { href: '/dashboard/intents', label: 'Intents' },
      { href: '/dashboard/knowledge', label: 'Knowledge Base' },
    ],
  },
  {
    label: 'Sales',
    items: [
      { href: '/dashboard/products', label: 'Products' },
      { href: '/dashboard/strategies', label: 'Upsell Strategies' },
      { href: '/dashboard/analytics', label: 'Sales Analytics' },
    ],
  },
  {
    label: 'Account',
    items: [
      { href: '/dashboard/usage', label: 'Usage & Billing' },
      { href: '/dashboard/settings', label: 'Settings' },
    ],
  },
]

const adminNav: NavGroup[] = [
  {
    label: 'Administration',
    items: [
      { href: '/dashboard', label: 'All Tenants' },
    ],
  },
]

export default function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const [isAdmin, setIsAdmin] = useState(false)
  const [managedName, setManagedName] = useState<string | null>(null)

  useEffect(() => {
    setIsAdmin(api.isAdmin())
    setManagedName(api.getManagedTenantName())
  }, [])

  const handleLogout = () => {
    api.clearToken()
    router.push('/login')
  }

  const handleBackToAdmin = () => {
    api.clearManagedToken()
    window.location.href = '/dashboard'
  }

  const showAdminOnly = isAdmin && !managedName
  const navGroups = showAdminOnly ? adminNav : tenantNav

  return (
    <aside className="w-64 bg-white border-r border-gray-200 min-h-screen p-4 flex flex-col">
      <div className="mb-6">
        <h2 className="text-lg font-bold text-gray-800">AI Concierge</h2>
        <p className="text-xs text-gray-500">
          {showAdminOnly ? 'Admin Panel' : 'Dashboard'}
        </p>
      </div>

      {isAdmin && managedName && (
        <div className="mb-4 p-3 bg-blue-50 rounded-lg border border-blue-200">
          <p className="text-xs text-blue-600 font-medium">Managing</p>
          <p className="text-sm font-semibold text-blue-800 truncate">{managedName}</p>
          <button
            onClick={handleBackToAdmin}
            className="mt-2 text-xs text-blue-600 hover:text-blue-800 font-medium"
          >
            &larr; Back to All Tenants
          </button>
        </div>
      )}

      <nav className="flex-1">
        {navGroups.map((group) => (
          <div key={group.label} className="mb-4">
            <p className="px-3 mb-1 text-xs font-semibold text-gray-400 uppercase tracking-wider">
              {group.label}
            </p>
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`block px-3 py-2 rounded-lg text-sm transition-colors ${
                    pathname === item.href
                      ? 'bg-blue-50 text-blue-700 font-medium'
                      : 'text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <button
        onClick={handleLogout}
        className="px-3 py-2 text-sm text-gray-500 hover:text-red-600 transition-colors text-left"
      >
        Sign Out
      </button>
    </aside>
  )
}
