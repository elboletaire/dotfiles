Testing notes
=============

Jest
----

### Mocking Date

As seen in [github][mocking dates]:

~~~javascript
it('creates a proper instance', () => {
  const dateToUse = new Date('2016')
  const tempDate = Date
  Date = class extends Date {
    constructor() {
      super()
      return dateToUse
    }
  }

  expect(new Date()).toEqual(dateToUse)

  // Reset Date object
  Date = tempDate
})
~~~

[mocking dates]: https://github.com/facebook/jest/issues/2234#issuecomment-308121037
