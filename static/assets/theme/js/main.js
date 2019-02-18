var fileForm = $('#fileform')
var userKeyword
if (fileForm.length) {
    var fileUploader = $('#fileupload')
    fileUploader.on('change', function () {
        var person = prompt("what clause or keywords are you looking for?", "")
        if (person != null) {
            userKeyword = person+""
        } else {
            userKeyword = ""
        }
        localStorage.setItem("prompt", userKeyword)
        $.ajax({
            url: "/store_txt",
            type: "get",
            data: { userKeyword: userKeyword },
            success: function(response) {
                console.log(response)
                fileForm.submit()
                $('#fileloader').addClass('ready')
                window.scrollTo(0, 0)
                $(document.body).css({
                    overflow: 'hidden'
                })                
            }
        })
    })
}
