'use client';

import { useState } from 'react';
import { useT } from '@/i18n/useT';

interface OnboardingStep {
  id: string;
  titleKey: string;
  descriptionKey: string;
}

const steps: OnboardingStep[] = [
  {
    id: 'welcome',
    titleKey: 'onboarding.welcome.title',
    descriptionKey: 'onboarding.welcome.description',
  },
  {
    id: 'company',
    titleKey: 'onboarding.company.title',
    descriptionKey: 'onboarding.company.description',
  },
  {
    id: 'team',
    titleKey: 'onboarding.team.title',
    descriptionKey: 'onboarding.team.description',
  },
  {
    id: 'courses',
    titleKey: 'onboarding.courses.title',
    descriptionKey: 'onboarding.courses.description',
  },
  {
    id: 'complete',
    titleKey: 'onboarding.complete.title',
    descriptionKey: 'onboarding.complete.description',
  },
];

export default function OnboardingWizard() {
  const { t } = useT();
  const [currentStep, setCurrentStep] = useState(0);
  const [formData, setFormData] = useState({
    companyName: '',
    companyLogo: null as File | null,
    departmentName: '',
    employees: [] as string[],
    courseTitle: '',
    courseDescription: '',
  });

  const handleNext = () => {
    if (currentStep < steps.length - 1) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleBack = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleComplete = () => {
    // Save onboarding data and redirect to dashboard
    console.log('Onboarding completed:', formData);
    window.location.href = '/dashboard';
  };

  return (
    <div className="max-w-2xl mx-auto p-6">
      {/* Progress bar */}
      <div className="mb-8">
        <div className="flex justify-between mb-2">
          {steps.map((step, index) => (
            <div
              key={step.id}
              className={`w-8 h-8 rounded-full flex items-center justify-center ${
                index <= currentStep
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-200 text-gray-600'
              }`}
            >
              {index + 1}
            </div>
          ))}
        </div>
        <div className="h-2 bg-gray-200 rounded">
          <div
            className="h-2 bg-blue-600 rounded transition-all"
            style={{ width: `${(currentStep / (steps.length - 1)) * 100}%` }}
          />
        </div>
      </div>

      {/* Step content */}
      <div className="mb-8">
        <h2 className="text-2xl font-bold mb-2">
          {t(steps[currentStep].titleKey)}
        </h2>
        <p className="text-gray-600">
          {t(steps[currentStep].descriptionKey)}
        </p>
      </div>

      {/* Form fields */}
      <div className="mb-8">
        {currentStep === 0 && (
          <div className="text-center py-8">
            <div className="text-6xl mb-4">🎓</div>
            <p className="text-lg text-gray-600">
              {t('onboarding.welcome.message')}
            </p>
          </div>
        )}

        {currentStep === 1 && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('onboarding.company.name')}
              </label>
              <input
                type="text"
                value={formData.companyName}
                onChange={(e) =>
                  setFormData({ ...formData, companyName: e.target.value })
                }
                className="w-full border rounded px-3 py-2"
                placeholder={t('onboarding.company.namePlaceholder')}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('onboarding.company.logo')}
              </label>
              <input
                type="file"
                accept="image/*"
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    companyLogo: e.target.files?.[0] || null,
                  })
                }
                className="w-full border rounded px-3 py-2"
              />
            </div>
          </div>
        )}

        {currentStep === 2 && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('onboarding.team.department')}
              </label>
              <input
                type="text"
                value={formData.departmentName}
                onChange={(e) =>
                  setFormData({ ...formData, departmentName: e.target.value })
                }
                className="w-full border rounded px-3 py-2"
                placeholder={t('onboarding.team.departmentPlaceholder')}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('onboarding.team.employees')}
              </label>
              <textarea
                value={formData.employees.join('\n')}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    employees: e.target.value.split('\n').filter(Boolean),
                  })
                }
                className="w-full border rounded px-3 py-2"
                rows={4}
                placeholder={t('onboarding.team.employeesPlaceholder')}
              />
              <p className="text-sm text-gray-500 mt-1">
                {t('onboarding.team.employeesHint')}
              </p>
            </div>
          </div>
        )}

        {currentStep === 3 && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('onboarding.courses.title')}
              </label>
              <input
                type="text"
                value={formData.courseTitle}
                onChange={(e) =>
                  setFormData({ ...formData, courseTitle: e.target.value })
                }
                className="w-full border rounded px-3 py-2"
                placeholder={t('onboarding.courses.titlePlaceholder')}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('onboarding.courses.description')}
              </label>
              <textarea
                value={formData.courseDescription}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    courseDescription: e.target.value,
                  })
                }
                className="w-full border rounded px-3 py-2"
                rows={4}
                placeholder={t('onboarding.courses.descriptionPlaceholder')}
              />
            </div>
          </div>
        )}

        {currentStep === 4 && (
          <div className="text-center py-8">
            <div className="text-6xl mb-4">🎉</div>
            <p className="text-lg text-gray-600">
              {t('onboarding.complete.message')}
            </p>
          </div>
        )}
      </div>

      {/* Navigation buttons */}
      <div className="flex justify-between">
        <button
          onClick={handleBack}
          disabled={currentStep === 0}
          className="px-4 py-2 border rounded disabled:opacity-50"
        >
          {t('common.back')}
        </button>

        {currentStep < steps.length - 1 ? (
          <button
            onClick={handleNext}
            className="px-4 py-2 bg-blue-600 text-white rounded"
          >
            {t('common.next')}
          </button>
        ) : (
          <button
            onClick={handleComplete}
            className="px-4 py-2 bg-green-600 text-white rounded"
          >
            {t('onboarding.complete.start')}
          </button>
        )}
      </div>
    </div>
  );
}
