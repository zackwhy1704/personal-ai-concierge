'use client'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { api } from '@/lib/api'

const navItems = [
  { href: '/dashboard', label: 'Overview' },
  { href: '/dashboard/guardrails', label: 'Guardrails' },
  { href: '/dashboard/intents', label: 'Intents' },
  { href: '/dashboard/knowledge', label: 'Knowledge Base' },
  { href: '/dashboard/usage', label: 'Usage & Billing' },
  { href: '/dashboard/settings', label: 'Settings' },
]

export default function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()

  const handleLogout = () => {
    api.clearToken()
    router.push('/login')
  }

  return (
    <aside className="w-64 bg-white border-r border-gray-200 min-h-screen p-4 flex flex-col">
      <div className="mb-8">
        <h2 className="text-lg font-bold text-gray-800">AI Concierge</h2>
        <p className="text-xs text-gray-500">Admin Dashboard</p>
      </div>

      <nav className="flex-1 space-y-1">
        {navItems.map((item) => (
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
