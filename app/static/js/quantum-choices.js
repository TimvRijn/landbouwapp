/**
 * Universal Quantum Choices.js Implementation
 * Plaats dit bestand in static/js/quantum-choices.js
 * 
 * Gebruik:
 * QuantumChoices.init(); // Initialiseer alle select elementen automatisch
 * QuantumChoices.create('#my-select', options); // Maak een specifieke select
 */

class QuantumChoices {
  constructor() {
    this.instances = new Map();
    this.defaultConfig = {
      searchEnabled: true,
      shouldSort: false,
      placeholder: true,
      removeItemButton: true,
      duplicateItemsAllowed: false,
      addItems: true,
      allowHTML: false,
      silent: false,
      renderChoiceLimit: 50,
      maxItemCount: -1,
      searchResultLimit: 4,
      searchFloor: 1,
      searchChoices: true,
      searchFields: ['label', 'value'],
      position: 'auto',
      resetScrollPosition: true,
      shouldSortItems: false,
      // Nederlandse teksten
      noResultsText: 'Geen resultaten gevonden',
      noChoicesText: 'Geen opties beschikbaar',
      itemSelectText: 'Klik om te selecteren',
      uniqueItemText: 'Alleen unieke waarden toegestaan',
      customAddItemText: 'Alleen waarden toegevoegd aan de lijst zijn toegestaan',
      addItemText: (value) => `Druk op Enter om "<b>${value}</b>" toe te voegen`,
      maxItemText: (maxItemCount) => `Maximaal ${maxItemCount} items toegestaan`,
      valueComparer: (choice1, choice2) => choice1 === choice2,
      fuseOptions: {
        includeScore: true
      },
      // Aangepaste templates
      callbackOnInit: function() {
        this.passedElement.element.setAttribute('data-quantum-choices', 'initialized');
        
        // Fix voor selected values - zorg dat de juiste waarde wordt getoond
        const selectedOption = this.passedElement.element.querySelector('option[selected]');
        if (selectedOption && selectedOption.value) {
          setTimeout(() => {
            this.setChoiceByValue(selectedOption.value);
          }, 100);
        }
      },
      callbackOnCreateTemplates: function(template) {
        return {
          item: ({ classNames }, data) => {
            return template(`
              <div class="${classNames.item} ${
                data.highlighted ? classNames.highlightedState : classNames.itemSelectable
              } ${
                data.placeholder ? classNames.placeholder : ''
              }" data-item data-id="${data.id}" data-value="${data.value}" ${
                data.active ? 'aria-selected="true"' : ''
              } ${
                data.disabled ? 'aria-disabled="true"' : ''
              }>
                ${data.label}
              </div>
            `);
          },
          choice: ({ classNames }, data) => {
            return template(`
              <div class="${classNames.item} ${classNames.itemChoice} ${
                data.disabled ? classNames.itemDisabled : classNames.itemSelectable
              }" data-select-text="${this.config.itemSelectText}" data-choice ${
                data.disabled ? 'data-choice-disabled aria-disabled="true"' : 'data-choice-selectable'
              } data-id="${data.id}" data-value="${data.value}" ${
                data.groupId > 0 ? 'role="treeitem"' : 'role="option"'
              }>
                ${data.label}
              </div>
            `);
          }
        };
      }
    };
  }

  /**
   * Initialiseer alle select elementen met de data-quantum-choices attribute
   */
  init() {
    // Wacht totdat de DOM geladen is
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => this._initializeElements());
    } else {
      this._initializeElements();
    }
  }

  /**
   * Initialiseer specifieke elementen
   */
  _initializeElements() {
    // Automatische initialisatie voor elementen met data-quantum-choices
    const autoElements = document.querySelectorAll('select[data-quantum-choices]:not([data-quantum-choices="initialized"])');
    autoElements.forEach(element => {
      this._createChoicesInstance(element);
    });

    // Initialisatie voor elementen met classes
    const classElements = document.querySelectorAll('select.quantum-choices:not([data-quantum-choices="initialized"])');
    classElements.forEach(element => {
      this._createChoicesInstance(element);
    });
  }

  /**
   * Maak een nieuwe Choices instance
   */
  create(selector, userConfig = {}) {
    const element = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (!element) {
      console.warn('QuantumChoices: Element not found:', selector);
      return null;
    }

    return this._createChoicesInstance(element, userConfig);
  }

  /**
   * Interne methode om een Choices instance te maken
   */
  _createChoicesInstance(element, userConfig = {}) {
    if (element.getAttribute('data-quantum-choices') === 'initialized') {
      return this.instances.get(element);
    }

    // Bewaar de originele selected value
    const originalValue = element.value;
    const selectedOption = element.querySelector('option[selected]');
    const preselectedValue = selectedOption ? selectedOption.value : originalValue;

    // Haal configuratie op uit data attributes
    const dataConfig = this._getDataConfig(element);
    
    // Merge configuraties
    const config = {
      ...this.defaultConfig,
      ...dataConfig,
      ...userConfig
    };

    // Maak Choices instance
    const choices = new Choices(element, config);
    
    // Sla instance op
    this.instances.set(element, choices);
    
    // Fix voor selected value - herstel na initialisatie
    if (preselectedValue) {
      setTimeout(() => {
        try {
          choices.setChoiceByValue(preselectedValue);
        } catch (error) {
          console.warn('QuantumChoices: Could not set preselected value:', preselectedValue);
        }
      }, 50);
    }
    
    // Voeg event listeners toe
    this._addEventListeners(element, choices);
    
    // Voeg utility methoden toe
    this._addUtilityMethods(choices);

    return choices;
  }

  /**
   * Haal configuratie op uit data attributes
   */
  _getDataConfig(element) {
    const config = {};
    const dataset = element.dataset;

    // Basis configuratie uit data attributes
    if (dataset.placeholder) config.placeholderValue = dataset.placeholder;
    if (dataset.searchPlaceholder) config.searchPlaceholderValue = dataset.searchPlaceholder;
    if (dataset.noResults) config.noResultsText = dataset.noResults;
    if (dataset.noChoices) config.noChoicesText = dataset.noChoices;
    if (dataset.maxItems) config.maxItemCount = parseInt(dataset.maxItems);
    if (dataset.searchEnabled !== undefined) config.searchEnabled = dataset.searchEnabled !== 'false';
    if (dataset.removeButton !== undefined) config.removeItemButton = dataset.removeButton !== 'false';
    if (dataset.shouldSort !== undefined) config.shouldSort = dataset.shouldSort === 'true';
    if (dataset.allowHtml !== undefined) config.allowHTML = dataset.allowHtml === 'true';
    if (dataset.duplicates !== undefined) config.duplicateItemsAllowed = dataset.duplicates === 'true';

    // States
    if (dataset.loading !== undefined) config.loading = dataset.loading === 'true';
    if (dataset.disabled !== undefined) config.disabled = dataset.disabled === 'true';

    // Styling
    if (dataset.size) {
      switch (dataset.size) {
        case 'small':
          element.classList.add('choices-small');
          break;
        case 'large':
          element.classList.add('choices-large');
          break;
      }
    }

    return config;
  }

  /**
   * Voeg event listeners toe
   */
  _addEventListeners(element, choices) {
    // Custom events
    element.addEventListener('change', (event) => {
      this._triggerCustomEvent(element, 'quantum:change', {
        value: event.target.value,
        choices: choices
      });
    });

    element.addEventListener('choice', (event) => {
      this._triggerCustomEvent(element, 'quantum:select', {
        choice: event.detail.choice,
        choices: choices
      });
    });

    element.addEventListener('removeItem', (event) => {
      this._triggerCustomEvent(element, 'quantum:remove', {
        item: event.detail,
        choices: choices
      });
    });

    element.addEventListener('search', (event) => {
      this._triggerCustomEvent(element, 'quantum:search', {
        query: event.detail.value,
        choices: choices
      });
    });

    // Loading state management
    if (element.dataset.loading === 'true') {
      choices.containerOuter.element.classList.add('is-loading');
    }

    // Fix voor dropdown positioning
    element.addEventListener('showDropdown', () => {
      this._fixDropdownPosition(choices);
    });
  }

  /**
   * Fix dropdown positioning om z-index conflicten te voorkomen
   */
  _fixDropdownPosition(choices) {
    const dropdown = choices.dropdown.element;
    if (dropdown) {
      // Zorg dat dropdown altijd zichtbaar is
      dropdown.style.zIndex = '9999';
      dropdown.style.position = 'absolute';
      
      // Controleer of dropdown buiten viewport valt
      setTimeout(() => {
        const rect = dropdown.getBoundingClientRect();
        const viewportHeight = window.innerHeight;
        
        if (rect.bottom > viewportHeight) {
          dropdown.style.top = 'auto';
          dropdown.style.bottom = '100%';
          dropdown.style.marginBottom = '4px';
          dropdown.style.marginTop = '0';
        }
      }, 10);
    }
  }

  /**
   * Voeg utility methoden toe aan de Choices instance
   */
  _addUtilityMethods(choices) {
    // Makkelijke state management
    choices.setLoading = (loading = true) => {
      if (loading) {
        choices.containerOuter.element.classList.add('is-loading');
      } else {
        choices.containerOuter.element.classList.remove('is-loading');
      }
    };

    choices.setError = (hasError = true) => {
      if (hasError) {
        choices.containerOuter.element.classList.add('has-error');
      } else {
        choices.containerOuter.element.classList.remove('has-error');
      }
    };

    choices.setSuccess = (hasSuccess = true) => {
      if (hasSuccess) {
        choices.containerOuter.element.classList.add('has-success');
      } else {
        choices.containerOuter.element.classList.remove('has-success');
      }
    };

    choices.setWarning = (hasWarning = true) => {
      if (hasWarning) {
        choices.containerOuter.element.classList.add('has-warning');
      } else {
        choices.containerOuter.element.classList.remove('has-warning');
      }
    };

    // Reset alle states
    choices.clearStates = () => {
      choices.containerOuter.element.classList.remove('is-loading', 'has-error', 'has-success', 'has-warning');
    };

    // Verbeterde setValue methode
    choices.setValue = (value) => {
      try {
        choices.setChoiceByValue(value);
        return true;
      } catch (error) {
        console.warn('QuantumChoices: Could not set value:', value, error);
        return false;
      }
    };

    // Laad opties van URL
    choices.loadFromUrl = async (url, valueKey = 'value', labelKey = 'label') => {
      choices.setLoading(true);
      try {
        const response = await fetch(url);
        const data = await response.json();
        
        choices.clearChoices();
        choices.setChoices(data.map(item => ({
          value: item[valueKey],
          label: item[labelKey],
          selected: false,
          disabled: false
        })), 'value', 'label', false);
        
        choices.setLoading(false);
      } catch (error) {
        console.error('QuantumChoices: Error loading from URL:', error);
        choices.setLoading(false);
        choices.setError(true);
      }
    };

    // Update placeholder
    choices.updatePlaceholder = (text) => {
      const placeholder = choices.containerInner.element.querySelector('.choices__placeholder');
      if (placeholder) {
        placeholder.textContent = text;
      }
    };
  }

  /**
   * Trigger custom event
   */
  _triggerCustomEvent(element, eventName, detail) {
    const event = new CustomEvent(eventName, {
      detail: detail,
      bubbles: true,
      cancelable: true
    });
    element.dispatchEvent(event);
  }

  /**
   * Krijg een Choices instance
   */
  getInstance(selector) {
    const element = typeof selector === 'string' ? document.querySelector(selector) : selector;
    return this.instances.get(element);
  }

  /**
   * Vernietig een Choices instance
   */
  destroy(selector) {
    const element = typeof selector === 'string' ? document.querySelector(selector) : selector;
    const choices = this.instances.get(element);
    if (choices) {
      choices.destroy();
      this.instances.delete(element);
      element.removeAttribute('data-quantum-choices');
    }
  }

  /**
   * Vernietig alle instances
   */
  destroyAll() {
    this.instances.forEach((choices, element) => {
      choices.destroy();
      element.removeAttribute('data-quantum-choices');
    });
    this.instances.clear();
  }

  /**
   * Herinitialiseer alle elementen (bijvoorbeeld na AJAX updates)
   */
  refresh() {
    this._initializeElements();
  }

  /**
   * Utility methoden voor formulier validatie
   */
  validateAll() {
    const results = [];
    this.instances.forEach((choices, element) => {
      const isValid = element.checkValidity();
      results.push({ element, choices, isValid });
      
      if (isValid) {
        choices.setSuccess(true);
        choices.setError(false);
      } else {
        choices.setError(true);
        choices.setSuccess(false);
      }
    });
    return results;
  }

  /**
   * Update configuratie van een bestaande instance
   */
  updateConfig(selector, newConfig) {
    const element = typeof selector === 'string' ? document.querySelector(selector) : selector;
    const choices = this.instances.get(element);
    if (choices) {
      // Bewaar huidige waarde
      const currentValue = choices.getValue();
      
      // Vernietig en hermaak
      choices.destroy();
      const newChoices = this._createChoicesInstance(element, newConfig);
      
      // Herstel waarde
      if (currentValue) {
        newChoices.setChoiceByValue(currentValue);
      }
      
      return newChoices;
    }
    return null;
  }
}

// Maak globale instance
window.QuantumChoices = new QuantumChoices();

// Auto-initialisatie wanneer script geladen wordt
if (typeof Choices !== 'undefined') {
  window.QuantumChoices.init();
} else {
  console.warn('QuantumChoices: Choices.js library not found. Please include Choices.js before quantum-choices.js');
}

// Export voor module gebruik
if (typeof module !== 'undefined' && module.exports) {
  module.exports = QuantumChoices;
}