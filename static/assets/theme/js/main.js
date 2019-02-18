var fileForm = $('#fileform')
var userKeyword
if (fileForm.length) {
    var fileUploader = $('#fileupload')
    fileUploader.on('change', function () {
        var person = prompt("what clause or keywords are you looking for?", "")
        if (person != null) {
            localStorage.setItem("prompt", person)
        } else {
            localStorage.setItem("prompt", "")
        }
        userKeyword = person;
        $.ajax({
            method: "POST",
            url: "/store_txt",
            data: { userKeyword: userKeyword }
        })
        .done(function( msg ) {
            // alert( "Data Saved: " + msg );            
            fileForm.submit()
            $('#fileloader').addClass('ready')
            window.scrollTo(0, 0)
            $(document.body).css({
                overflow: 'hidden'
            })
        });
    })
}
